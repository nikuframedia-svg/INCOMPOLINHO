# Causas comprovadas dos casos de planeamento

Verificação de 01/10/2026. Dataset `6d55d4d1d9094833aebdf62d89297d52`,
ISOP `ISOP_Nikufra_17.09.xlsx`, plano ativo na revisão 89, 558 segmentos.
Os ensaios comparativos usaram cópias em memória e leitura SQLite. A publicação
das proteções abaixo conservou esse plano.

## 1. Um plano fisicamente inválido foi aceite

A revisão 70, guardada em 17/09 às 14:20 UTC, contém nove violações da capacidade
de operadores. O seu relatório persistido diz `physical_gate_passed=true`.
A validação atual do mesmo snapshot encontra nove conflitos
`operator_capacity` e rejeita a ativação. A revisão 71 passou a respeitar a
capacidade, mas mudou a alocação de produções urgentes.

O defeito de persistência estava em `backend/plans/store.py`: os métodos
`save(activate=True)`, `commit_mutation` e `commit_load` confirmavam snapshots
sem validar novamente os recursos físicos do payload exato. A integridade dos
fingerprints prova que os dados não mudaram; não prova que o plano seja viável.

Correção publicada: os três caminhos validam segmentos, lotes, quantidades,
dados canónicos, operadores, calendários e âncoras manuais antes da gravação.
Um relatório antigo de aprovação não permite contornar essa validação. Um
payload com produção é validado mesmo sem identificador do dataset; apenas a
configuração sem plano fica dispensada. A falha conserva o ponteiro ativo e
não confirma o snapshot ou o recibo.

Regressão: `tests/test_plan_transactions.py` cobre máquina indisponível e falta
de operadores, com e sem identidade, nos três caminhos. Os testes de candidatos
e carregamento foram corrigidos para usar durações coerentes com OEE 0,66.

## 2. Reparações parciais reescreveram dias já passados

A comparação dos snapshots encontrou sete lotes alterados retroativamente.
Entre as revisões 87 e 88, guardadas em 01/10, cinco lotes de setembro mudaram,
incluindo a transferência da BFP079 da PRM039 para a PRM031. Nas revisões
81–83 também mudaram tempos de setup e distribuição da BFP082; na revisão 86
foi antecipada a BFP112 de 22/09 para 21/09.

Esse procedimento libertou capacidade passada sem reconstruir de forma
coerente todas as decisões que tinham sido tomadas à volta dela. Os outros
lotes continuaram protegidos pela regra de preservar lotes iniciados. As
lacunas resultantes persistiram no snapshot apresentado ao utilizador.

Correção já publicada: a persistência compara o histórico com o plano ativo e
recusa alterações retroativas, alterações do calendário que desloquem o
histórico e novas produções no passado. As explicações do Gantt distinguem
planeamento passado de execução confirmada. Anotações antigas não são usadas
como prova da capacidade atual.

## 3. O que isto explica nos exemplos

| Caso | Evidência | Consequência |
|---|---|---|
| VUL195 e VUL174 em 25/09 | Na revisão 77 a BFP079 ocupava a PRM039 durante todo o dia 8. A transferência posterior libertou esse período já passado. | A máquina agora parece livre, mas os outros lotes mantêm as posições históricas. O intervalo não prova uma indisponibilidade atual. |
| BFP083 em 29/09 | Existe a âncora `LOT_TWIN_BFP083_15`, PRM031, início produtivo `2026-09-29T15:30`, motivo `teste`, autor `utilizador`, guardada em 25/09. | O início está fixado por uma decisão manual. Antecipá-lo exige rever essa decisão; uma máquina livre não a invalida. |
| BFP082 para entrega em D0 | O plano antigo com melhor OTD era fisicamente inválido. Num ensaio com os inputs da revisão 71, preservar a campanha da BFP082 em D0 produziu um plano válido, mas com 14 encomendas atrasadas, contra 8 no plano de referência. | Há um compromisso de entregas comprovado nessa alternativa. O ensaio não prova ótimo global nem que todas as antecipações possíveis tenham sido pesquisadas. |

O ensaio de compactação sobre a revisão 77, simulando o dia 8 e retirando as
ausências, conservou os lotes já iniciados e terminou com zero conflitos
físicos. A BFP079 ocupava a PRM039 nesse dia; esse ensaio não representa a
lacuna criada pela transferência retroativa de outubro.

## 4. Verificação e limite da entrega

- Backend completo: 1940 testes passaram, um ignorado.
- Após fechar o contorno por identidade ausente: 229 regressões focadas
  passaram, uma ignorada.
- Frontend: 122 testes passaram; TypeScript e build passaram; Ruff dos
  ficheiros alterados e `git diff --check` passaram.
- Corrigido o contexto de apresentação do relatório: o plano já ativo deixou
  de anunciar que ainda pode ser aplicado. As pré-visualizações conservam a
  mensagem de aprovação. Verificado numa cópia isolada a 390 e 1440 px.
- Snapshot real da revisão 70: rejeitado pelos nove conflitos de operadores.
- Snapshot ativo da revisão 89: validado; identidade e 558 segmentos
  conservaram-se após o reinício do backend.
- Backup consistente: `INCOMPOLINHO-backups/20261001T1817-durable-validation`.
- Navegação de leitura em Hoje, Plano, Capacidade, Entregas, Risco e
  Configuração passou no acesso local e público, a 390 e 1440 px. A identidade
  e o plano conservaram-se; não houve erros de página ou de API.

Estas verificações provam as proteções publicadas. Não demonstram que os
horários históricos tenham sido reconstruídos ou que o plano seja ótimo.
A aplicação não guarda execução efetiva de produção. Para corrigir também as
lacunas históricas, é necessário esclarecer se setembro é uma simulação de
planeamento ou produção que realmente ocorreu. Esse esclarecimento determina
se o passado pode ser reconstruído ou deve ser conservado.

## 5. Ensaios retrospectivos completos, ainda isolados

Foi retirado o congelamento apenas nas cópias de ensaio, mantendo a âncora
manual da BFP083. Estes candidatos não substituíram a revisão 89 publicada.

| Ensaio | Tempo | Validade física | Entregas | Setups | Transferências |
|---|---|---|---|---|---|
| Reconstrução desde D0 | 58,34 s | Sem conflitos | OTD 96,5%; atraso total 33, antes 37 | 197 / 9210 min, antes 195 / 9075 min | 21, antes 14 |
| Compactação dos lotes existentes | 19,16 s | Sem conflitos | Nenhuma encomenda piora; OTD 96,5%; atraso total 37 | 194 / 9015 min | 10 |

São medições individuais, não médias. A pesquisa terminou por orçamento e não
constitui prova de ótimo global. A reconstrução inicia a BFP082 em D0, mas
aumenta setups: não é uma melhoria automática admissível face ao plano ativo.
A compactação conserva identidades, quantidades e outputs gémeos e consegue
colocar VUL195 e VUL174 na PRM039 em D8. Também antecipa a BFP080 em D11.
Contudo, desloca a BFP112 de D4 para D6, mantendo a entrega no prazo. Portanto,
não prova que todos os pedidos de antecipação possam ser satisfeitos juntos.

A aplicação isolada apresentou os dois lotes VUL em 25/09 a 390 e 1440 px.
A navegação de leitura pelas seis páginas passou sem erros de página ou API.
O plano público manteve 558 segmentos; o ensaio tem 554. Uma imagem do ensaio
nunca deve ser descrita como atualização já aplicada no link público.

## 6. Outra causa na seleção do candidato

Em `backend/replan/jobs.py`, quando os inputs eram comparáveis, a seleção
comparava sobretudo `delivery_not_worse`. Esse critério agregado não bastava
para o contrato de melhoria automática: podia aceitar um candidato com mais
setups ou com perda numa encomenda compensada pelo ganho noutra. Além disso,
uma compactação com entregas iguais era substituída pelo plano original,
mesmo que tivesse aproveitado melhor os intervalos livres.

Dois testes reproduziram falhas no código anterior: descarte da compactação
melhor e contagem de um movimento revertido por timeout como aceite no
relatório por âmbito. A correção publicada reutiliza `plan_facts`,
`no_loss_verdict` e `improvement_key`; preserva a compactação admissível melhor
e conserva a referência quando o cálculo não demonstra ganho sem perdas.
O rollback do coordenador também repõe os contadores por âmbito.

Um terceiro teste cobre encomendas individuais com o mesmo OTD agregado.
A comparação é limitada aos inputs efetivamente comparáveis; não usa o plano
antigo como alternativa quando uma alteração de OEE ou capacidade o invalida.

## 7. Verificação da publicação adicional

- Backend completo na cópia isolada: 1944 testes passaram, um ignorado,
  em 420,09 s. As regressões focadas do bloco passaram: 117 testes.
- Frontend: 122 testes passaram; TypeScript e build passaram. Ruff dos
  ficheiros alterados e `git diff --check` passaram.
- Após integrar os ficheiros verificados: 44 regressões de replaneamento e
  melhoria passaram na árvore publicada.
- Backup consistente antes de publicar:
  `INCOMPOLINHO-backups/20261001T1858-comparison`.
- Backend reiniciado; comparação antes/depois confirmou os mesmos dados,
  revisão, segmentos, lotes, configuração, indicadores, mutações e decisões
  manuais. Revisão 89, 558 segmentos: nenhum candidato de ensaio foi aplicado.
- Navegador pelo mesmo link público: Hoje, Plano, Carga e capacidade,
  Entregas, Risco e Configuração passaram a 390 e 1440 px, sem erros de página
  ou API. Todas as escritas foram bloqueadas pelo ensaio.
- Duas tentativas iniciais do ensaio tinham uma barra duplicada no URL da
  consulta (`//api/data/plan-view`), que devolvia o HTML da aplicação. O erro
  estava no endereço do teste, não no endpoint. O script agora normaliza a
  barra final do URL de entrada.

Continua pendente a decisão sobre a reconstrução do passado. A publicação
corrige a seleção de candidatos e a integridade dos relatórios; não faz os
horários de setembro desaparecerem nem altera uma decisão manual já guardada.

## 8. Conservação da produção e limites dos movimentos

A investigação adicional usou `/tmp/incompolinho-manual-audit`, uma cópia
isolada do código e das bases. Foram reproduzidos defeitos distintos dos
horários históricos:

- `backend/plans/manual_move.py` aceitava o candidato do otimizador quando o
  alvo e os gates físicos estavam corretos, sem verificar a identidade e as
  obrigações dos restantes lotes. Um candidato podia renomear outro lote ou
  redistribuir as quantidades entre dois lotes, mantendo a procura total. O
  caminho de realocação com lote fixo verificava apenas IDs e quantidades.
- `backend/scheduler/improvement.py` também podia aceitar uma renomeação com
  melhor entrega. Além disso, a cópia de trabalho partilhava os marcos de
  entrega e os metadados aninhados de lotes e segmentos com a referência. Um
  gerador rejeitado podia modificar esses dados na referência conservada.
- O timeout do otimizador não abrangia toda a verificação de movimento. Os
  caminhos alternativos podiam continuar após os 60 segundos, e um
  cancelamento posterior ao cálculo podia ainda devolver uma pré-visualização.
- A comparação de movimento omitia a ocupação e as contagens de material; os
  valores por omissão apresentavam 0%, mesmo com produção positiva.

Correções publicadas neste bloco:

1. Contrato comum `production_lot_obligations`, em
   `backend/scheduler/canonical.py`, conserva IDs, operação, ferramenta,
   quantidade, outputs gémeos, prazos, marcos e obrigações de subcontratação.
   A alocação e as durações dependentes da máquina podem mudar; a produção
   original não pode ser recriada. Movimentos e melhorias verificam esse
   contrato e a cobertura das quantidades antes de aceitar o resultado.
2. As tentativas de melhoria usam cópias independentes dos lotes e dos marcos
   dos segmentos. A rejeição deixa intactos os dados da referência.
3. O movimento usa um único prazo exterior de 60 segundos, incluindo os
   caminhos alternativos e a validação, com dez segundos reservados após a
   pesquisa inicial. Os ciclos de materialização verificam prazo e
   cancelamento. O trabalho apresenta timeout como verificação inconclusiva,
   sem declarar impossibilidade física nem disponibilizar aplicação.
4. A comparação reutiliza o cálculo de ocupação do simulador e transporta as
   contagens reais de violações de material. O título da janela existente
   quebra linha sem se sobrepor ao botão de fechar em 390 px. Não foram
   acrescentados cartões ou alteradas preferências industriais.

Regressões permanentes em `tests/test_manual_move.py`,
`tests/test_improvement_cycle.py`, `frontend/tests/MoveLotModal.test.tsx` e
`frontend/tests/Modal.test.tsx` cobrem as reproduções acima.

### Verificação deste bloco

- Backend completo: 1953 testes passaram, um ignorado, em 429,69 s.
- Após integração: 133 regressões focadas passaram. Ruff passou.
- Frontend: 124 testes de interface e 22 de lógica passaram; TypeScript,
  ESLint e build passaram. Mantêm-se os avisos anteriores de depreciação do
  TestClient e de tamanho do bundle.
- Percurso real de pré-visualização e aplicação, apenas na instância isolada:
  `LOT_VUL192_PRM019_8750787433_25`, do dia 20 para dia 21, PRM019, início
  produtivo 14:00. A execução final demorou 22,04 s; outras duas execuções
  individuais demoraram 21,03 e 26,16 s. Não constituem benchmark p50/p95.
  O resultado respeitou o alvo, os gates físicos, os 202 IDs, quantidades e
  outputs. A ocupação apresentada passou de 58,89% para 59,07%, não 0%.
  Uma preparação adicional exigiu a aprovação existente e foi aceite apenas
  no ensaio manual. Nenhum candidato deste ensaio foi aplicado em produção.
- Screenshots e verificação de geometria a 390 e 1440 px confirmaram ausência
  de sobreposição entre título e botão. Não houve erros de página.
- Antes da publicação: snapshot ativo validado sem conflitos físicos,
  quantidades em falta ou violação de âncoras; nenhum trabalho ativo ou journal
  pendente. Backup de código, configuração, regras e quatro bases SQLite:
  `INCOMPOLINHO-backups/20261001T1934-manual-contract`.
- Backend e frontend reiniciados nas portas 8010/53868; túnel conservado. O
  frontend era um serviço transitório e teve de ser recriado após a paragem,
  com o mesmo nome, diretório e porta. A comparação antes/depois confirmou
  dataset, revisão, segmentos, lotes, configuração, indicadores, mutações e
  decisões manuais intactos.
- Navegação final local e pública em Hoje, Plano, Carga e capacidade,
  Entregas, Risco e Configuração passou a 390 e 1440 px, com todas as escritas
  bloqueadas pelo ensaio. Uma primeira passagem pública apresentou falha de
  ligação ao consultar a Configuração em 390 px, sem resposta HTTP de erro
  registada; a repetição integral passou. Isto não demonstra a causa dessa
  falha de rede. Relatórios finais:
  `/tmp/incompolinho-manual-local-final.json` e
  `/tmp/incompolinho-manual-public-final-retry.json`.
  A leitura pública após esses ensaios voltou a confirmar revisão 89 e os
  mesmos 558 segmentos, incluindo os horários históricos.

Este bloco elimina os contornos reproduzidos, mas não prova ótimo global nem
que todos os movimentos encontrem solução. Os horários históricos e a âncora
BFP083 continuam preservados. A decisão sobre reconstruir setembro continua
pendente do esclarecimento indicado na secção 4.

## 9. O contrato residual escondia perdas no plano completo

Novo bloco desenvolvido e verificado em `/tmp/incompolinho-merged-audit`,
publicado em 01/10/2026 após a verificação isolada e o backup abaixo.

### Causa e reprodução

`backend/plans/frozen.py::_install_frozen_reservations` reserva a procura dos
lotes protegidos mediante `CommittedSupply(available_day=0)`. Essa reserva
evita produzir novamente a mesma quantidade no problema residual; não é uma
data real de conclusão da produção. Contudo, `improve_plan` utilizava esses
inputs residuais também para avaliar entregas e decidir se havia perdas.

A reprodução permanente usa identificadores genéricos, duas máquinas, três
lotes e duas referências. Um lote protegido produz 100 peças de A em D6.
Outro lote de A produz 100 peças em D4; a primeira encomenda precisa delas em
D5. B produz em D7 para entrega em D5. A proposta troca A para D7 e B para D4.
No problema residual, a reserva fictícia de A em D0 mascara a perda: B melhora
e a proposta é aceite. No plano completo, A perde 100 peças no prazo e atrasa
um dia. O teste falhou no código anterior e passou após a correção.

### Correção comum

- O coordenador conserva os recursos reservados para gerar propostas, mas
  avalia cada proposta sobre o plano completo, com as datas reais da produção
  protegida e os inputs canónicos. Serviço por encomenda, setups, ranking,
  assinaturas e explicações usam esse mesmo estado completo.
- A compactação após libertação de capacidade passa exclusivamente pelo
  coordenador. Foram retiradas reparações anteriores e posteriores que
  estavam fora desse contrato. As rotinas existentes continuam disponíveis
  como propostas; não foram criadas exceções por ferramenta.
- A junção final valida novamente o contrato completo. Se falhar, mantém a
  referência e repõe contadores, resumo e assinatura; não anuncia movimentos
  descartados como aceites.
- Ao atingir o limite de propostas de uma rotina, o relatório indica
  `partial/search_limit`, com `limited_by_scope`. Continua a testar as outras
  rotinas; não confunde uma pesquisa truncada com pesquisa concluída.

As duas reproduções de rollback e as três verificações de pesquisa truncada
também falharam no código anterior. As regressões estão em
`tests/test_merged_improvement_contract.py` e `tests/test_improvement_cycle.py`.
A reserva em D0 permanece exclusivamente como mecanismo de conservação da
procura; não foi substituída por uma alteração às regras industriais.

### Verificação isolada

- Backend completo: 1960 testes passaram, um ignorado, em 423,30 s.
- Frontend: 124 testes de interface e 22 de lógica passaram; ESLint,
  TypeScript e build passaram. Ruff dos cinco ficheiros Python passou.
- Dez compactações antes e dez depois, com a revisão 89, congelamento fixo em
  D14, mesmos dados e configuração: todas fisicamente válidas, sem perdas por
  encomenda, IDs e quantidades conservados, referência intacta e resultados
  repetíveis dentro de cada versão. Depois: p50 1,744 s, p95 1,893 s; antes:
  p50 2,410 s, p95 2,594 s. Memória máxima do processo ~122 MiB nas duas versões.
  As versões foram medidas com carga concorrente no servidor. São medições
  deste percurso, não a duração média de todos os cálculos da aplicação.
  O script `scripts/benchmark_improvement.py` lê apenas o snapshot ativo e
  mede a memória Linux por `VmHWM`, evitando herdar o pico do processo lançador.
- Movimento real no frontend isolado: VUL192, D20 para D21, PRM019, 14:00,
  pré-visualização em 24,77 s; aplicação com a aprovação já existente. Os 202
  lotes e quantidades mantiveram-se; gates físico e de cobertura passaram.
  A revisão 90 e os 546 segmentos resultantes pertencem apenas à cópia isolada.
- Navegação nas seis páginas, a 390/1440 px, passou na instância isolada após
  aplicação, sem erros de página ou API. Artefactos:
  `/tmp/incompolinho-merged-frontend-check.json`,
  `/tmp/incompolinho-merged-local-final.json`,
  `/tmp/incompolinho-merged-performance-before.json` e
  `/tmp/incompolinho-merged-performance-after.json`.

Estas provas eliminam o contorno reproduzido; não atribuem todos os intervalos
das fotografias a esta causa nem provam ótimo global. O plano histórico de
setembro e a âncora manual continuam protegidos como explicado nas secções 2–4.

### Publicação Confirmada

- Nenhum trabalho em cálculo ou journal pendente no preflight; os candidatos
  antigos existentes na base pertencem a outras revisões. A lista de trabalhos
  pendentes da revisão ativa estava vazia.
- Backend parado brevemente para backup consistente de código, configuração,
  regras e quatro bases SQLite, todas com `integrity_check=ok`:
  `INCOMPOLINHO-backups/20261001T2000-merged-contract`.
- Integrados apenas os cinco ficheiros Python deste bloco e os dois documentos.
  Backend reiniciado na porta 8010; frontend na 53868 e túnel permaneceram
  ativos, sem alterações de código frontend nesta publicação.
- Comparação antes/depois confirmou dataset, revisão, segmentos, lotes,
  configuração, indicadores, mutações e decisões manuais idênticos. Plano
  público: revisão 89, 558 segmentos, 202 lotes. Nenhum ensaio foi aplicado.
- Após integração: 98 regressões focadas passaram; Ruff e diff-check passaram.
  Os cinco ficheiros Python publicados coincidem com os verificados na cópia.
- Navegador pelo mesmo link público: seis páginas a 390/1440 px passaram sem
  erros de página ou API; o teste bloqueou todas as escritas. Relatório:
  `/tmp/incompolinho-merged-public-final.json`.

## 10. Um filtro confundia o fim do lote com a entrega da encomenda

Bloco desenvolvido em `/tmp/incompolinho-proposal-audit` e publicado em
01/10/2026, depois dos ensaios isolados. Não foi recalculado nem substituído
o plano público.

### Causa demonstrada

`backend/scheduler/transfer_consolidation.py::_late_lots` comparava o último
dia de produção de um lote com o seu prazo de produção. Os dois percursos de
consolidação, local e de bloco, descartavam a proposta se esse fim passasse
para um dia posterior. O comentário do código inferia daí que uma encomenda
ficaria atrasada, antes de consultar o avaliador comum.

Essa inferência não é válida para um lote que abastece várias encomendas:
a quantidade necessária para o prazo inicial pode estar pronta, mesmo que
a cauda destinada a uma encomenda posterior termine mais tarde. Uma rotina
de propostas não deve sobrepor esse indicador aproximado ao contrato real.

A reprodução permanente usa duas máquinas e identificadores genéricos:

- P precisa de 100 peças em D0, 100 em D1 e 100 em D3. O primeiro lote
  produz 100 em D0; o segundo produz 100 em D0 e 100 em D2.
- A alternativa conserva as primeiras 200 peças em D0 e termina as últimas
  100 em D3. Todas as encomendas de P continuam satisfeitas no prazo.
- A mesma alternativa antecipa a produção urgente de U de D2 para D0,
  elimina uma transferência e reduz três setups físicos para dois.
- O filtro antigo rejeitava-a apenas porque o segundo lote acabaria em D3
  em vez de D2. A alternativa é fisicamente válida e melhora o contrato.
- Na variante negativa, as 100 peças necessárias em D1 só ficam prontas
  em D2. O avaliador comum rejeita-a, mesmo com o ganho de U.

Os quatro testes parametrizados falharam no código anterior e passam no
novo, com dois conjuntos de IDs. A reprodução injeta uma alocação conhecida
na construção de propostas para isolar o filtro, mas verifica a sua
legalidade e o serviço por encomenda antes de executar o coordenador.
Não prova que a pesquisa limitada encontre todas as alocações possíveis.

### Correção e limites

- Retirado `_late_lots` e os dois filtros de atraso pelo fim integral do lote.
- Conservados os filtros de recursos, proteção histórica, setups e benefício.
- A decisão final continua no mesmo avaliador do plano completo: quantidade
  por encomenda, atraso individual, subcontratação, setups e hierarquia fixa.
- Não foram alteradas preferências nem criadas exceções para BFP079,
  BFP082 ou qualquer outra ferramenta.

Regressão: `tests/test_transfer_consolidation.py::test_lot_completion_is_not_proof_of_a_customer_delivery_loss`.
Este defeito podia excluir melhorias legítimas; não demonstra que cada
intervalo das fotografias tenha esta causa. Os horários históricos continuam
protegidos, conforme as secções 2–4, e não se afirma ótimo global.

### Testes e medições

- Backend completo isolado: 1963 passaram, dois ignorados, em 420,68 s.
  Um ignorado é o ensaio opt-in de 151 segundos; o outro precisava da base
  real, excluída inicialmente da cópia. Esse teste real foi depois executado
  sobre uma cópia SQLite e passou. Nenhuma falha funcional ficou neste bloco.
- Frontend: 124 testes de interface e 22 de lógica passaram; lint,
  TypeScript/build e Ruff passaram. O build mantém o aviso preexistente
  do bundle superior a 500 kB, sem erro de compilação.
- Dez compactações antes e dez depois, mesmos inputs da revisão 89 e
  congelamento D14: todos os resultados válidos, sem perdas, IDs/quantidades
  conservados, referência intacta e assinatura repetível. Antes: p50 1,716 s,
  p95 1,864 s, RSS 121,66 MiB. Depois: p50 2,394 s, p95 2,778 s,
  RSS 121,91 MiB. Retirar o filtro implica avaliar mais hipóteses: esta
  correção não é um ganho de velocidade. A alocação desse benchmark manteve
  a mesma assinatura. Estas medições, com carga concorrente, não representam
  todos os cálculos nem todos os ISOP.
- Frontend isolado: VUL192, D20 para D21, PRM019, 14:00; pré-visualização
  em 20,55 s, aplicação do candidato com aprovação existente, revisão 90.
  Os 202 lotes e quantidades mantiveram-se; gates físico/cobertura passaram.
  Verificados modal e navegação nas seis páginas a 390/1440 px.
- A primeira tentativa do navegador isolado encontrou uma página vazia e
  expirou ao procurar a navegação. Não foi demonstrada a causa dessa falha.
  Uma verificação independente carregou a aplicação; a repetição integral
  passou, sem erros de página. A falha inicial não foi tratada como sucesso.

Artefactos: `/tmp/incompolinho-proposal-full.xml`,
`/tmp/incompolinho-proposal-frontend-check.json`,
`/tmp/incompolinho-proposal-local-final.json`,
`/tmp/incompolinho-proposal-performance-before.json` e
`/tmp/incompolinho-proposal-performance-after.json`.

### Publicação verificada

- Preflight sem trabalhos em cálculo nem journal por confirmar; nenhuma
  pré-visualização pendente na revisão ativa. Código e plano não tinham
  mudado durante a verificação.
- Backup consistente de código/configuração/regras e quatro bases SQLite,
  todas com `integrity_check=ok`:
  `/home/luis/projects/INCOMPOLINHO-backups/20261001T2023-transfer-delivery`.
- Publicados apenas o gerador corrigido, o ficheiro de regressão e estes
  registos. Backend reiniciado em 8010; frontend e túnel mantidos.
- Os dois ficheiros Python publicados coincidem com os ensaiados; 83
  regressões passaram após integração. Diff-check passou.
- Comparação antes/depois: dataset, revisão, segmentos, lotes, configuração,
  indicadores, mutações e decisões manuais idênticos. Plano público:
  revisão 89, 558 segmentos, 202 lotes.
- Mesmo link público: seis páginas a 390/1440 px passaram, sem erros de
  página/API. Todas as escritas estavam bloqueadas no navegador de ensaio.
  Relatório: `/tmp/incompolinho-proposal-public-final.json`.

## 11. Pesquisa limitada não é prova de impossibilidade

Bloco desenvolvido em `/tmp/incompolinho-scope-audit` e publicado em
01/10/2026, sem recalcular nem substituir o plano público.

### Causas demonstradas no código

- `consolidation_proposals` analisava apenas as primeiras 24 hipóteses sem
  comunicar as restantes ao coordenador. Podia devolver `completed` apesar
  de não ter analisado todas as hipóteses do seu próprio âmbito.
- Limites de 14 dias na comparação local e de seis campanhas relacionadas
  eram devolvidos como propostas ignoradas comuns. O coordenador não
  distinguia uma comparação truncada de uma comparação concluída.
- A cache guardava motivo e detalhes, mas não a informação de truncagem.
  A reutilização podia voltar a apresentar uma comparação incompleta como
  concluída. Um bloco integral com sete campanhas também podia entrar na
  reconstrução, contrariando o limite declarado de seis (§5.3).
- A explicação `unschedulable` afirmava que não havia espaço após falhar
  uma heurística limitada. Essa falha não constitui prova de impossibilidade
  física. A explicação `contract` dizia sempre que haveria atraso, mesmo
  quando a razão calculada era um aumento de setups.
- Configuração e o componente de relatório existente não mostravam o estado
  parcial quando não havia uma lista de transferências a apresentar.

### Correção estrutural

- `SkippedProposal.scope_limited` transporta a truncagem de forma explícita,
  incluindo a cache. O coordenador continua a analisar as outras hipóteses
  e só conclui a ronda sem ganhos como `completed` se nenhum âmbito ficou
  incompleto. Caso contrário, devolve `partial/search_limit`.
- Um limite encontrado num estado anterior não torna incompleta uma ronda
  posterior inteiramente analisada sobre outro estado. Uma compactação de
  fecho incompleta devolve o último candidato integralmente estabilizado,
  sem guardar um movimento de grupo parcialmente verificado.
- Blocos maiores que seis campanhas não entram na reconstrução integral;
  a tentativa local de conservar a primeira campanha continua disponível.
- A explicação passa a dizer que não encontrou alocação no âmbito
  verificado, ou que a comparação ficou incompleta. A perda de contrato
  apresenta a razão efetivamente calculada, não um atraso presumido.
- A indicação «melhoria parcialmente verificada» aparece na linha de
  métricas/estado já existente. Não foram criados cartões nem alteradas
  permissões, aprovações, restrições ou preferências industriais.

### Regressões e ensaios

- 14 novos casos backend: cap de hipóteses, sete campanhas, truncagem local
  e integral, cache, continuação da pesquisa, estado anterior, compactação
  interrompida e explicações. As reproduções funcionais falham no código
  anterior; três testes de integração falham inicialmente pela ausência
  do novo campo de contrato, não por um erro de alocação diferente.
- Cinco novos casos frontend, incluindo recuperação de candidato parcial
  em Configuração sem bloquear a aplicação permitida pelas regras atuais.
- Backend completo isolado: 1977 passaram, dois ignorados, em 454,58 s.
  O teste da cópia real SQLite, inicialmente ignorado por falta da base na
  árvore isolada, foi depois executado e passou. O outro é o ensaio opt-in
  de 151 segundos. Frontend: 129 testes de interface e 22 de lógica passaram;
  lint, TypeScript/build e Ruff passaram. Mantém-se o aviso preexistente
  de bundle superior a 500 kB.
- Dez compactações antes/depois sobre a revisão 89: todos os resultados
  fisicamente válidos, sem perdas, com IDs/quantidades conservados e origem
  intacta. Mesma alocação nos dois códigos; o relatório incorreto
  `completed` passou corretamente a `partial/search_limit`. Antes: p50
  2,771 s, p95 3,286 s, RSS 121,60 MiB. Depois: p50 2,893 s, p95 3,389 s,
  RSS 121,83 MiB. São ensaios de compactação com carga concorrente, não
  médias de todos os cálculos nem evidência de aumento de velocidade.
- Frontend real isolado: movimento VUL192 D20 para D21, PRM019, 14:00,
  pré-visualização em 23,61 s e aplicação do candidato exato, revisão 90;
  os 202 lotes e quantidades mantiveram-se. Esse percurso não devolveu
  `gate_report.improvement`; portanto não comprova a nova mensagem parcial.
  A propagação desse campo no movimento permanece um ponto de auditoria.
- Prova da mensagem com resposta real: PRM039 OEE 0,65, candidato pronto
  em 57,93 s, gates físico/cobertura aprovados, melhoria `partial/budget`.
  A mensagem aparece a 390/1440 px. O candidato foi cancelado, e o snapshot
  isolado ficou intacto. Não foi aplicado OEE nem movimento em produção.
- Navegação isolada nas seis páginas a 390/1440 px passou, sem erros de
  página/API; todas as escritas estavam bloqueadas nessa verificação.

Artefactos: `/tmp/incompolinho-scope-full.xml`,
`/tmp/incompolinho-scope-performance-before.json`,
`/tmp/incompolinho-scope-performance-after.json`,
`/tmp/incompolinho-scope-frontend-check.json`,
`/tmp/incompolinho-scope-config-check.json` e
`/tmp/incompolinho-scope-local-final.json`.

Este bloco elimina conclusões injustificadas sobre a pesquisa limitada.
Não prova um ótimo global nem reconstrói os horários históricos das fotos.
A auditoria integral continua em curso.

### Publicação e verificação

- Preflight validou o snapshot ativo com o código novo: zero conflitos
  físicos, de quantidade ou de âncora. Sem cálculos ativos, journal preparado
  ou candidatos prontos na revisão atual; fontes verificadas sem alterações
  concorrentes antes da integração.
- Backup consistente de código/configuração/regras, estado auxiliar e quatro
  bases SQLite, todas com `integrity_check=ok`:
  `/home/luis/projects/INCOMPOLINHO-backups/20261001T2048-search-scope`.
- Backend e frontend foram parados brevemente, integrados apenas oito
  ficheiros de código/testes e estes registos, e reiniciados nas portas
  existentes. O túnel e o link não foram alterados. A tentativa de recriar
  o serviço frontend transitório foi recusada porque a unidade ainda estava
  carregada; reiniciar a própria unidade existente resolveu esse passo.
- Os oito ficheiros publicados coincidem com os ensaiados. Após integração,
  111 regressões backend e 25 frontend passaram; diff-check passou.
  Relatórios: `/tmp/incompolinho-scope-integrated.xml` e
  `/tmp/incompolinho-scope-integrated-ui.json`.
- A primeira verificação pública abriu um ecrã vazio e expirou a procurar
  «Hoje», sem erros de página/API registados. Os dados desse ensaio não
  demonstram a causa. O carregamento independente, local e pelo túnel,
  apresentou a aplicação sem falhas de pedidos ou execução. A repetição
  integral nas seis páginas a 390/1440 px passou; não se considera o primeiro
  ensaio um sucesso nem se afirma eliminada a causa da abertura vazia.
  Relatórios preservados: `/tmp/incompolinho-scope-public-final.json`
  (falha) e `/tmp/incompolinho-scope-public-repeat.json` (passou).
- Dataset, revisão, segmentos, lotes, configuração, indicadores, mutações e
  decisões manuais ficaram idênticos. Plano público: revisão 89, 558
  segmentos, 202 lotes. Todas as escritas foram bloqueadas no ensaio público.

## 12. O movimento manual contornava o fecho comum

Bloco desenvolvido em `/tmp/incompolinho-manual-cycle`. Os ensaios e
aplicações abaixo pertencem à instância isolada, não ao plano público.

### Reprodução e causa

`manual_move.py::_replan_around_fixed_lot` chamava `optimize` sobre a parte
residual, incluindo a fase de melhorias, antes de juntar o lote fixado e o
histórico. Depois reconstruía o relatório de gates sem transportar o resumo
de melhorias. A tentativa estrita de recurso materializava o lote pedido,
mas devolvia esse plano sem passar pelo fecho comum: capacidade libertada
por retirar um lote podia continuar desaproveitada.

Uma reprodução com IDs genéricos fixa LOT1 em M2, D1, às 10:00. A máquina
M1 fica disponível e um segundo lote, colocado em D3 e devido em D2, pode
antecipar-se. O código anterior mantinha D3. A correção usa o mesmo contrato
e antecipa esse lote, mantendo LOT1 exatamente na posição pedida, todas as
quantidades e as entradas originais intactas. A reprodução passa também
com outro identificador, sem exceções por ferramenta.

Outro defeito reproduzido estava no recuo: o coordenador restaurava candidato
e contagens após uma compactação interrompida, mas mantinha o registo de
propostas aceites no estado abandonado. A rejeição do plano combinado tinha
o mesmo problema. A explicação podia, assim, chamar aceite a um movimento
que não existia no resultado devolvido.

### Correções e limites

- A construção residual com lote fixado usa `improve=False`. A melhoria
  acontece quando existe o candidato completo, através de
  `improve_preserving_protected_lots`, com as reservas e o avaliador comuns.
- O lote pedido e as outras posições manuais/históricas ficam protegidos.
  Quantidades e IDs são novamente verificados antes da pré-visualização.
- Um relatório anterior só é reutilizado se corresponder à assinatura física
  exata desse candidato completo. Isto evita repetir uma fase já verificada
  ou atribuir ao plano combinado a verificação de uma parte residual.
- A fase usa até dez segundos dentro do orçamento exterior de 60, com
  margem de fecho de cinco. Sem margem, indica `not_evaluated/no_time_left`.
  Não reinicia o relógio, não contorna cancelamento nem baixa aprovações.
- O relatório vai para `gate_report.improvement`, que o modal existente já
  apresenta. Não foram acrescentados cartões nem alteradas preferências.
- O recuo para o último estado estabilizado repõe também o seu registo de
  propostas. A rejeição do plano combinado elimina as entradas aceites que
  foram retiradas do resultado.

### Verificação

- Cinco novos casos e duas regressões reforçadas falharam no código anterior:
  antecipação nos dois IDs, relatório do candidato exato, adiamento da fase
  residual e registo após recuo. Dois casos adicionais verificam relatório
  obsoleto e ausência de orçamento para a fase final.
- Um teste antigo de reparação do setup exigia que a produção restante
  começasse às 08:00, deixando o intervalo libertado vazio. Agora verifica
  o início às 07:00, conservando os 30 minutos de setup, a quantidade e
  a validade física. Não foi relaxada uma restrição industrial.
- 101 regressões focadas passaram. Backend completo: 1984 passaram, dois
  ignorados, em 449,15 s. O teste real SQLite ignorado foi depois executado
  sobre a cópia isolada e passou; permanece ignorado o ensaio opt-in de
  151 segundos. Frontend: 130 testes de interface e 22 de lógica passaram;
  lint, TypeScript/build e Ruff passaram, com o aviso preexistente de bundle.
- Navegador real: VUL192, D20 para D21, PRM019, 14:00. Pré-visualização
  pronta em 34,14 s; sete melhorias adicionais, setups físicos 196 para 195
  e transferências 29 para 17, comparados com o candidato fixado antes da
  melhoria. OTD/OTD-D e atrasos mantidos. A hora pedida e os 202 lotes foram
  conservados; gates físico/cobertura aprovados; estado `partial/budget`
  visível no modal a 390/1440 px. Aplicação na cópia: revisão 89 para 90,
  553 segmentos, com a aprovação existente. Não foi aplicada em produção.
- Seis páginas isoladas a 390/1440 px passaram sem erros de página/API.
- Dez movimentos sobre a revisão 89 antes e dez depois: todos válidos,
  hora exata, IDs/quantidades preservados e origem intacta, abaixo de 62 s.
  Antes: p50 23,196 s, p95 23,888 s, RSS 154,70 MiB. Depois: p50 32,936 s,
  p95 36,248 s, RSS 160,06 MiB, sete ou nove melhorias aceites e estado
  parcial nas dez. A fase adicional tem custo; não se afirma ganho de
  velocidade. As assinaturas completas incluem UUIDs do movimento e não
  provam aleatoriedade da alocação. Estes ensaios não provam determinismo
  temporal de uma pesquisa interrompida pelo orçamento. O script permanente
  inclui também assinatura física nas execuções futuras.
- Cinco aberturas independentes do link público passaram, entre 0,55 e
  0,96 s, com registo de console, pedidos falhados e respostas HTTP.
  Isso não demonstra a causa nem elimina a falha inicial da secção 11.

Artefactos: `/tmp/incompolinho-manual-cycle-before.xml`,
`/tmp/incompolinho-manual-cycle-full.xml`,
`/tmp/incompolinho-manual-cycle-real.xml`,
`/tmp/incompolinho-manual-cycle-frontend-check.json`,
`/tmp/incompolinho-manual-cycle-local-final.json`,
`/tmp/incompolinho-manual-cycle-performance-before.json`,
`/tmp/incompolinho-manual-cycle-performance-after.json` e
`/tmp/incompolinho-public-load-probe.json`.

A correção fecha uma divergência entre percursos, não demonstra que cada
fotografia histórica tenha a mesma causa. A auditoria integral e a decisão
sobre reconstrução dos horários históricos continuam pendentes.

### Publicação e verificação

- O snapshot ativo passou a validação física, de cobertura e de âncoras
  com o código novo. Não havia cálculos ativos, operações preparadas nem
  candidatos prontos na revisão atual. Os hashes dos ficheiros confirmaram
  ausência de alterações concorrentes no âmbito integrado.
- O backend foi parado brevemente para backup consistente de código,
  configuração, regras, estado auxiliar e quatro bases SQLite, todas com
  `integrity_check=ok`:
  `/home/luis/projects/INCOMPOLINHO-backups/20261001T2129-manual-complete`.
- Foram integrados apenas oito ficheiros de código/testes e três documentos.
  O backend reiniciou na porta existente. O frontend, sem alteração de
  código de aplicação neste bloco, e o túnel mantiveram-se em funcionamento.
  A primeira tentativa de aplicar o diff foi recusada pelo formato do
  cabeçalho, antes de editar os ficheiros; o patch corrigido foi aplicado.
- Os onze ficheiros coincidiram com a cópia ensaiada. Após integração,
  139 regressões backend e 34 frontend passaram. O comando `pnpm` não
  estava disponível; os testes de integração frontend foram executados
  diretamente com a versão local de Vitest e passaram. Diff-check passou;
  os avisos de limpeza de diretórios temporários do pytest não são falhas
  funcionais. Relatórios: `/tmp/incompolinho-manual-cycle-integrated.xml`
  e `/tmp/incompolinho-manual-cycle-integrated-ui.json`.
- As seis páginas do link público passaram a 390/1440 px, sem erros de
  página/API nem escritas. Dataset, revisão, segmentos, lotes, configuração,
  indicadores, mutações e decisões manuais permaneceram iguais à captura
  anterior. Revisão 89, 558 segmentos, 202 lotes.
- Relatório público: `/tmp/incompolinho-manual-cycle-public-final.json`.
  A imagem `/tmp/incompolinho-manual-cycle-preview-1440.png` documenta
  a pré-visualização real isolada, não uma alteração ao plano de produção.

Este bloco foi publicado no mesmo link. A publicação não converte
automaticamente horários históricos nem conclui os restantes requisitos
da auditoria integral.

## 13. Montagem anterior e preparação repartida divergiam

Bloco desenvolvido em `/tmp/incompolinho-retained-move`. A aplicação
`Regressao_setup.xlsx` é uma fixture isolada, não o ISOP público.

### Causa e reprodução

`manual_move.py::_materialize_target` começava sempre pelo máximo dos minutos
nominais do lote e do run, sem verificar a afinação efetivamente montada.
Uma produção podia terminar às 08:30 e outra da mesma referência/molde ser
pedida exatamente às 08:30. O código exigia preparação antes dessa hora,
encontrava a máquina ocupada e devolvia «Não há capacidade física», embora
a instalação anterior fosse reutilizável.

No scheduler, `_remove_redundant_retained_tool_setups` procurava o segmento
anterior sem excluir o próprio run em análise. Num setup de 60 minutos
repartido em 30 no turno A e 30 no turno B, a primeira parte era interpretada
como prova de instalação anterior: a segunda era eliminada indevidamente.
Quando havia realmente uma instalação compatível anterior, só era retirada
a preparação do segmento produtivo; o fragmento apenas de setup ficava.

Cinco execuções de regressão falharam no código anterior: o pedido na fronteira
ocupada com dois identificadores, o percurso completo desse movimento, e os
dois sentidos da limpeza de setup repartido. Não é uma preferência para uma
ferramenta específica nem uma modificação apenas visual.

### Correção estrutural

- `setup_identity.retained_setup_at` centraliza a verificação da montagem:
  mesma máquina e identidade de afinação, sem uso do molde noutra máquina
  no intervalo. A preparação do próprio run não comprova instalação anterior;
  uma preparação parcial também não basta.
- O movimento manual consulta esse estado antes de reservar tempo de setup.
  A hora pedida, duração produtiva, quantidades e gémeas continuam intactas;
  mantém-se a validação física final e o contrato do candidato completo.
- A limpeza automática conserva todas as partes de um setup necessário ou
  elimina todas as partes da preparação redundante. Fragmentos puramente de
  setup retirados deixam de ocupar o calendário; a produção já alocada só é
  antecipada pela normalização com recursos.
- Mantêm-se afinações entre referências incompatíveis, reinstalações depois
  de transferência e proteção integral dos lotes/run históricos ou fixados.
  Não foram criados cartões, exceções por SKU ou novas preferências.
- O script de navegação passou a ler a máquina do snapshot. A primeira
  verificação genérica expirou porque procurava PRM031 numa fixture M1/M2;
  isso era uma suposição do ensaio, não uma falha da aplicação. O artefacto
  falhado permanece em `/tmp/incompolinho-retained-move-local-final.json`.

### Verificação

- 186 regressões focadas passaram; 12 casos novos cobrem as cinco reproduções,
  afinação, outro molde, transferência, preparação incompleta, família de
  setup, gémeas e preparação concluída.
- Backend completo: 1997 passaram, um ignorado (ensaio opt-in de 151 segundos),
  em 521,25 s. O teste SQLite real passou também isoladamente; a cópia da base
  foi disponibilizada antes da execução desse caso na suíte completa.
- Frontend: 130 testes de interface e 22 de lógica passaram. Lint,
  TypeScript/build e Ruff passaram; permanece o aviso preexistente do bundle.
- Navegador real isolado: LOT1 pedido em M1, D0, 08:30, pronto em 0,915 s.
  O candidato foi aplicado com a aprovação existente, revisão 1 para 2.
  Produção anterior termina às 08:30, LOT1 começa às 08:30 sem setup adicional;
  duas quantidades de 100 conservadas e apenas os 30 minutos de preparação
  inicial. Dados guardados e Gantt coincidem a 390/1440 px.
- Dez repetições do movimento VUL192, D20 para D21, PRM019, 14:00, sobre uma
  cópia da revisão 89: todas fisicamente válidas, com cobertura, IDs e
  quantidades preservados, origem intacta e tempo inferior a 62 segundos.
  p50 32,715 s, p95 34,062 s, RSS máximo 156,61 MiB. O bloco anterior registou
  p50 32,936 s/p95 36,248 s; concorrência e diferenças de pesquisa impedem
  atribuir a diferença a um ganho de velocidade.
- As dez pesquisas terminam parciais por orçamento, com sete ou nove melhorias.
  Existem duas assinaturas físicas, ambas validadas: não se afirma que uma
  pesquisa interrompida tenha sempre a mesma alocação nem que encontre o ótimo.

Artefactos: `/tmp/incompolinho-retained-move-before.xml`,
`/tmp/incompolinho-retained-move-focused.xml`,
`/tmp/incompolinho-retained-move-full.xml`,
`/tmp/incompolinho-retained-move-real.xml`,
`/tmp/incompolinho-retained-move-browser.json` e
`/tmp/incompolinho-retained-move-real-performance.json`.

Ainda falta auditar a classificação dos restantes insucessos da pesquisa
manual: a ausência de candidato numa heurística limitada não prova
impossibilidade. Esta correção elimina as causas reproduzidas acima, não
atribui automaticamente essa causa a todas as fotografias históricas.

## 14. Falha local de movimento apresentada como impossibilidade global

Bloco de 02/10, desenvolvido em `/tmp/incompolinho-move-verdict`.
Não altera a hierarquia de objetivos nem reconstitui os horários de setembro.

### Causa comprovada

`manual_move.py::_move_lot` tenta otimização, depois realocação em torno do
lote fixado e, finalmente, uma colocação com os restantes lotes nas posições
originais. A última tentativa propagava `ManualMoveError` de falta de capacidade
como resposta ao pedido completo. Falhar nessa vizinhança limitada não prova
que uma reorganização mais ampla seja impossível.

Dois casos com identificadores diferentes comprovam a divergência: o alvo
é pedido em M2, D1, às 10:00; outro lote ocupa esse instante, mas pode ser
deslocado para as 12:10. O plano testemunho conserva IDs, quantidades e prazo,
e passa validação física e cobertura. Quando a pesquisa não encontra um
candidato completo, o código anterior declarava falta de capacidade física.
Quatro outros testes mostram que recursos indisponíveis e decisões protegidas
só eram diagnosticados depois de iniciar uma pesquisa desnecessária.
As seis execuções falharam antes da correção.

### Correção

- Uma pré-verificação usa o calendário efetivo e as proteções existentes para
  demonstrar impedimentos no instante pedido: fábrica fechada, máquina ou
  ferramenta indisponível, conflito com produção protegida e operadores
  insuficientes após ausências/produção protegida. Identifica recurso,
  data/hora e, nos bloqueios de recurso ou lote, intervalo.
- Lotes futuros não protegidos não são usados como prova de impossibilidade.
  A tentativa com outras posições fixas fica numa fronteira explícita.
  Falha da pesquisa ou candidato rejeitado na validação final produz
  `ManualMoveInconclusive`, sem candidato nem gate reutilizável para aplicar.
- Trabalhos assíncronos mostram «Verificação inconclusiva». A rota antiga
  mantém 409 com `code=verification_inconclusive`; timeout exterior conserva
  504. Cancelamento, proteção histórica e aprovação de riscos não mudam.
- O navegador encontrou outra falha: `invalidatePreview` retirava o resultado
  ao editar, mas conservava o erro do pedido anterior. Agora invalida também
  esse erro. Dois testes de interface cobrem o resultado inconclusivo e a edição.

### Verificação antes de integrar

- 122 regressões focadas passaram. Backend completo: 2005 passaram, um
  ignorado (ensaio HTTP opt-in de 151 segundos), em 402,62 segundos.
- Frontend: 132 testes de interface e 22 de lógica passaram; lint,
  TypeScript/build e Ruff passaram. Aviso preexistente de bundle acima de 500 kB.
- Navegador real, fixture genérica `Regressao_movimento.xlsx`, a 390/1440 px:
  pedido das 10:00 inconclusivo em 0,956 s, plano intacto e sem aplicação;
  editar para 11:40 retirou o aviso antigo; candidato válido aplicado na
  instância isolada, revisão 1 para 2, IDs e quantidades conservados.
- O primeiro ensaio esperava um nome acessível exatamente igual a «Máquina»,
  ignorando o texto das opções do select: falha no seletor antes do POST.
  A repetição revelou o aviso antigo não invalidado; artefacto preservado em
  `/tmp/incompolinho-move-verdict-browser-first.json`. O percurso completo
  corrigido passou em `/tmp/incompolinho-move-verdict-browser.json`.
- Ensaio único na cópia do ISOP real: VUL192, D20 para D21, PRM019, 14:00,
  30,86 s, RSS 154,67 MiB; candidato físico e cobertura válidos, 202 lotes
  e quantidades conservados, origem intacta. Melhoria parcial por orçamento;
  esta medição individual não é média nem prova de ganho de velocidade.
- Pré-publicação: snapshot ativo 89 validado, 558 segmentos/202 lotes,
  configuração e decisões manuais iguais à captura; sem trabalhos SQLite
  ativos nem journal preparado. Nenhum ensaio substituiu o plano público.

Artefactos: `/tmp/incompolinho-move-verdict-before.xml`,
`/tmp/incompolinho-move-verdict-focused.xml`,
`/tmp/incompolinho-move-verdict-full.xml`,
`/tmp/incompolinho-move-verdict-real-performance.json`.

Esta correção torna a conclusão verdadeira; não transforma uma busca
heurística em solver exaustivo e não garante encontrar todas as alternativas.
O fecho dos restantes âmbitos da auditoria integral continua por demonstrar.

### Publicação verificada

- Backup consistente de código/configuração/regras e quatro bases SQLite:
  `INCOMPOLINHO-backups/20261002T0026-move-verdict`.
- Nove ficheiros integrados com hashes e contexto preservado; os restantes
  ficheiros da árvore pública coincidiram com a cópia validada.
- Backend/frontend reiniciados nas mesmas portas e túnel. Após integração,
  158 regressões backend e 15 testes de interface passaram.
- Hoje, Plano, Capacidade, Entregas, Risco e Configuração no mesmo link
  público passaram a 390/1440 px, sem erros de página/API ou escritas.
  Relatório: `/tmp/incompolinho-move-verdict-public-final.json`.
- Snapshot ativo, revisão 89, 558 segmentos e 202 lotes permaneceram iguais;
  configuração, indicadores, mutações e decisões manuais não foram alterados.
  A imagem `/tmp/incompolinho-move-verdict-inconclusive-1440.png` mostra a
  fixture isolada, não uma alteração do ISOP público.

### Publicação e verificação

- Snapshot ativo validado pelo código novo: zero conflitos físicos, de
  cobertura ou de âncoras. Nenhum trabalho ativo, operação preparada ou
  candidato pronto na revisão atual; hashes sem alterações concorrentes.
- Backup consistente de código/configuração/regras, estado auxiliar e quatro
  bases SQLite com `integrity_check=ok`:
  `/home/luis/projects/INCOMPOLINHO-backups/20261001T2158-retained-setup`.
- Backend parado brevemente e reiniciado na porta existente; frontend e
  túnel continuaram ativos. Integrados apenas seis ficheiros de código/testes
  e três documentos, coincidentes com a cópia ensaiada.
- Após integração, 234 regressões backend, Ruff e diff-check passaram.
  Relatório: `/tmp/incompolinho-retained-move-integrated.xml`.
- As seis páginas públicas passaram a 390/1440 px, sem erros de página/API
  nem escritas. Dataset, revisão, segmentos, lotes, configuração, indicadores,
  mutações e decisões manuais ficaram iguais à captura anterior.
  Revisão 89, 558 segmentos, 202 lotes. Relatório:
  `/tmp/incompolinho-retained-move-public-final.json`.
- A repetição de navegação genérica isolada também passou, depois de retirar
  a suposição PRM031 do script:
  `/tmp/incompolinho-retained-move-local-repeat.json`.
  Print do resultado aplicado apenas na fixture:
  `/tmp/incompolinho-retained-move-applied-1440.png`.

Publicado no mesmo link; não substitui o plano ativo nem conclui a auditoria
integral. As pendências de prova estão explicitadas no documento de progresso.

## 15. O instante livre para produzir era usado para começar a preparação

Na enumeração de casos pequenos surgiu outra causa demonstrada de intervalos
evitáveis. `gap_filling._candidate_boundaries` recolhia os instantes de mudança
dos recursos, mas `find_opening_gap_opportunities` usava-os exclusivamente como
inícios do bloco setup + produção. Uma libertação de operadores às 08:30
originava setup às 08:30 e produção às 09:00, mesmo podendo preparar a máquina
das 08:00 às 08:30. Equipa de setup e operadores de produção são recursos
distintos nas regras existentes; o validador já distinguia os dois intervalos,
mas o gerador não lhe apresentava a hipótese correta.

O defeito aparecia no detetor, normalização e ciclo comum de melhoria. Este
último podia anunciar `completed`, pois o encaixe nem sequer era gerado. Seis
reproduções falharam antes da correção, com duas ferramentas/horários distintos
e um candidato físico completo comprovado em cada caso. Não é uma exceção
de BFP079, BFP080 ou de OEE.

Correção em `backend/scheduler/gap_filling.py`:
- Eventos canónicos partilhados através de `candidate_interval_boundaries`.
- `candidate_setup_starts` testa tanto o evento como evento menos duração de
  setup, com arredondamento conservador e limites do turno. Continua a existir
  validação integral de máquina, ferramenta, preparação, operadores e material.
- Os eventos de fim de preparação fracionada são arredondados para cima.
- Operações comprovadamente sem setup nos inputs canónicos também podem ser
  antecipadas. Um prefixo com zero setup de uma continuação não permite inventar
  uma montagem anterior: conservam-se os caminhos de campanha existentes.
- `explainability.py` consulta os mesmos eventos e hipóteses, incluindo ausências
  e reservas históricas; não conserva uma enumeração independente de recursos.

`tests/test_setup_boundary_search.py`: 23 casos, incluindo comparação com uma
enumeração ao minuto de inícios de um bloco completo nas pequenas fixtures,
ausência de operadores, máquina, ferramenta, equipa reservada, setup zero,
conservação de inputs/quantidades, permutação de listas e idempotência. A
enumeração é apenas um oráculo de teste, não o algoritmo da aplicação.

Na fixture privada `Regressao_setup.xlsx`, o percurso do movimento existente
fixou a outra produção na sua posição original; o fecho automático antecipou
`LOT1` para D0, setup 08:00–08:30, produção 08:30–09:30. Pré-visualização em
0,907 s, aplicação apenas na cópia, IDs/quantidades/entregas e um setup mantidos.
Dados guardados e geometria da faixa no Gantt coincidiram a 390/1440 px.
As seis páginas também passaram após reiniciar a instância privada.

Dez compactações de uma cópia do ISOP, com corte histórico D14: todas físicas,
sem perdas por encomenda/setup, obrigações conservadas e origem intacta.
Antes: p50 2,488 s, p95 2,694 s, RSS máximo 121,91 MiB. Depois: p50 2,538 s,
p95 2,889 s, RSS máximo 122,05 MiB. Mesmo fingerprint nas vinte execuções.
São medições deste percurso/cópia, não a média dos recálculos de produção nem
prova de aceleração; não se reconstruíram os horários históricos de setembro.

Artefactos: `/tmp/incompolinho-setup-boundaries-before.xml`,
`/tmp/incompolinho-setup-boundaries-focused.xml`,
`/tmp/incompolinho-setup-boundaries-browser.json`,
`/tmp/incompolinho-setup-boundaries-applied-1440.png`,
`/tmp/incompolinho-setup-boundaries-real-performance.json` e respetivo `-before`.

## 16. A validação da configuração alterava o próprio snapshot

O primeiro arranque da fixture privada revelou uma causa distinta:
`deserialize_config` fazia apenas `dict(raw)`, conservando as referências a
`tools` e `setup_overrides`. `normalize_config_numbers` alterava esses objetos
aninhados durante a validação física de `PlansStore.save(activate=True)` ou
`commit_mutation`, depois de verificar a integridade. Um valor inteiro válido,
por exemplo setup `0`, tornava-se `0.0` no payload; o fingerprint anterior
permanecia. O escritor aceitava-o, mas o arranque recusava o snapshot ativo com
`fingerprint da configuração não confere`.

Agora `deserialize_config` copia profundamente o input antes de normalizar.
Não se desativa a verificação de integridade nem se modifica o payload já
assinado. Quatro regressões permanentes falharam antes e passaram depois:
leitura dos dois campos numéricos aninhados e gravação/commit com reabertura
da base. A comparação usa JSON, pois igualdade de dicionários confunde 0 e 0.0.
O arranque da fixture aplicada passou também no navegador após reiniciar.

A suíte inicial deste bloco teve 2031 testes passados e uma falha de expectativa
antiga: `test_replan_does_not_restore_delivery_floor_that_is_physically_invalid`
exigia o score fictício 90%, mesmo após uma antecipação válida. O teste conserva
a recusa do plano antigo inválido e passa a validar o candidato persistido,
comparando o OTD devolvido com o scoring desse candidato. Não se alteram gates
ou critérios industriais para acomodar o teste.

## 17. Timeout podia encaminhar para uma alocação truncada

A regressão completa seguinte teve 2031 testes passados, um ignorado e uma
falha física no cenário de cinco máquinas com ferramentas partilhadas. A
repetição controlada também falhou no código público anterior. O rastreio
mostrou que a perda não ocorria nas novas antecipações: o candidato já
chegava incompleto da fase JIT.

O solver global tem um orçamento curto nas pequenas instâncias. Quando não
obtinha candidato, `_calendar_preemptive_fallback` só era admitido se houvesse
um calendário de indisponibilidades. Sem essas entradas, `jit_dispatch` seguia
o alocador antigo, que termina em `engine_data.n_days`, embora possa haver
procura cuja produção legal termine depois. O comportamento dependia de o
solver conseguir ou não um candidato dentro do tempo: não era uma mudança
das preferências por referência. Na falha observada faltavam 12033 peças;
a validação final impediu publicar esse resultado como plano físico válido.

Agora a construção completa já existente é usada depois de a pesquisa global
não encontrar candidato, também sem indisponibilidades. Mantém os calendários,
materiais, operadores, equipa, duração na máquina escolhida, horizonte
diagnóstico limitado e checkpoints de cancelamento/tempo existentes. O
candidato só é devolvido após `assert_plan_valid`, incluindo cobertura.
`UNKNOWN` não passa a `INFEASIBLE`: quando há atraso, timeout conserva
`timeout_with_candidate` e uma mensagem de verificação inconclusiva. As
interrupções de calendário são contadas pelo valor real, sem inventar uma.

Três regressões controladas falharam antes da correção: procura maior do que
o horizonte inicial com `UNKNOWN` e `INFEASIBLE`, e o cenário completo das
cinco máquinas forçando `UNKNOWN`. Após corrigir, 158 testes de JIT, scheduler
e fallback passaram. A suíte completa final com `PYTHONHASHSEED=0` terminou
com 2035 testes passados, um ignorado, em 427,43 s. Frontend: 22 testes de
lógica e 132 de interface passados; lint, TypeScript, build e Ruff passaram.
Permanecem os avisos preexistentes de httpx/Starlette e dimensão do bundle.
Artefactos: `/tmp/incompolinho-setup-boundaries-fallback-before.xml`,
`/tmp/incompolinho-setup-boundaries-fallback-focused.xml` e
`/tmp/incompolinho-setup-boundaries-full-release.xml`.
A navegação privada com o código final passou após reinício a 390/1440 px,
sem erro de página/API ou escrita: revisão 3 e dois segmentos conservados.
Relatório: `/tmp/incompolinho-setup-boundaries-local-release.json`.

### Publicação Das Secções 15–17

- Antes de parar o backend, e novamente com o serviço parado, confirmados
  revisão 89, dataset, ponteiro ativo, ausência de trabalhos/candidatos ativos
  ou operações preparadas, hashes e zero violações físicas/cobertura/âncoras.
- Backup consistente de código, configuração, regras, estado auxiliar e
  quatro bases SQLite com `integrity_check=ok`:
  `/home/luis/projects/INCOMPOLINHO-backups/20261002T0130-setup-boundaries`.
- Integrados só dez ficheiros: quatro de backend, quatro de testes e dois
  documentos. Backend reiniciado na porta 8010; frontend sem alterações de
  código, reiniciado na porta 53868. Túnel e URL preservados.
- A primeira consulta pública coincidiu com o arranque e recebeu 502;
  o artefacto ficou em `/tmp/incompolinho-setup-boundaries-public-final.json`.
  Após confirmar o health local e a conclusão do arranque, as seis páginas
  públicas passaram a 390/1440 px, sem erros de página/API nem escritas:
  `/tmp/incompolinho-setup-boundaries-public-repeat.json`.
- Após integração: 180 regressões backend, Ruff e diff-check passaram.
  Houve avisos de limpeza de diretórios temporários do pytest, sem falhas.
  Relatório: `/tmp/incompolinho-setup-boundaries-integrated.xml`.
- Dataset, revisão, 558 segmentos físicos, 202 lotes, configuração,
  indicadores, mutações e decisões manuais iguais à captura anterior. Só
  `left_shift_blockers` mudou em 108 segmentos: explicações recalculadas no
  arranque pelo enumerador corrigido. A comparação de todos os restantes
  campos dos segmentos é exata, sem ignorar horários, máquinas ou quantidades.
  Relatório: `/tmp/incompolinho-setup-boundaries-state-diff.json`.
  O novo código validou o plano ativo sem o substituir. Históricos de setembro
  não foram reconstruídos; os prints da antecipação são da fixture isolada.

Publicado no mesmo link. Este bloco não conclui a auditoria integral; as
pendências e a questão sobre simulação/produção histórica continuam explícitas
no documento de progresso.

## 18. Arredondamentos divergentes nos recursos de setups fracionários

Estado: correção publicada e verificada no mesmo link em 02/10/2026.
Não é prova de que todos os casos das fotografias tenham esta mesma causa.

O oráculo exploratório da secção 15 foi convertido em 33 testes permanentes.
No código público anterior, 27 falharam e seis passaram. Na cópia corrigida,
os 33 passaram, incluindo 1840 comparações de intervalos com um oráculo
independente de ocupação. Não se arredonda o oráculo com as funções do motor.

### Causa E Exemplo Reproduzido

O contrato já admite durações de setup fracionárias, mas os seus consumidores
não usavam a mesma fronteira entre preparação e produção:

- `gap_filling.evaluate_legal_interval` arredondava o setup proposto para cima
  e o fim do setup de outros lotes para baixo.
- `operators.operator_peaks`, movimentos manuais e reservas de lotes
  protegidos usavam `round`; a construção preemptiva usava `ceil`.
- A projeção de reservas no modelo inteiro do solver truncava o fim, podendo
  libertar a equipa antes de terminar uma preparação protegida.
- A pesquisa de equipa também usava `round`: uma hipótese antes de a equipa
  ficar livre era recusada, sem testar o primeiro minuto inteiro seguinte.

Exemplo: um operador fica livre às 09:12 (minuto 552). Uma preparação começa
às 08:29 (509), dura 42,5 minutos e termina às 09:11:30 (551,5). O início
produtivo sobrepõe-se meio minuto à outra produção. O avaliador arredondava a
preparação para 43 minutos e dizia que não havia conflito; o indicador também
arredondava o início produtivo para 552. O inverso foi reproduzido: terminar
antes do fim do setup de outro lote podia ser recusado por antecipar a reserva
dos seus operadores. Não se trata de uma preferência industrial por ferramenta.

### Correção Comum, Sem Alterar Regras

`Segment.production_start_min` fornece a fronteira física sem arredondamento.
O avaliador, indicadores e reservas protegidas usam-na. As reservas de equipa
preservam a sua duração exata; no modelo CP-SAT inteiro o bloqueio cobre todo
o intervalo físico, com início arredondado para baixo e fim para cima.

Movimentos e construção preemptiva reutilizam `operator_free_windows`, em vez
de dois cálculos diferentes. O sweep de eventos conserva frações, soma a
produção concorrente e as ausências e junta as parcelas livres adjacentes.
Só no fim converte para janelas contidas nessa disponibilidade na grelha de
minutos: início para cima, fim para baixo. Juntar antes de arredondar evita
perder minutos livres por causa de eventos irrelevantes de outros lotes.

O enumerador conserva eventos fracionários até descontar o setup; as hipóteses
de relógio continuam inteiras. A pesquisa e as explicações conservam também
a duração fracionária do setup. Não se alteram quantidades, identificadores,
prioridades, aprovações ou limites de capacidade; não há novas componentes UI.

### Verificação Já Executada

- 33 testes novos passaram; os 1840 intervalos enumerados cobrem quatro setups,
  com/sem ausência, e a produção concorrente começa a meio minuto.
- 263 regressões focadas passaram antes de acrescentar as últimas comparações
  e três verificações do solver. Suíte completa: 2067 testes passados, dois
  ignorados, sem falhas, em 411,30 s. O teste real ignorado por ausência da
  base na cópia passou depois sobre backup SQLite consistente. O outro é o
  ensaio opt-in de 151 segundos. Frontend: 154 testes, lint, TypeScript e build
  passaram; Ruff passou. Mantêm-se os avisos preexistentes httpx/bundle.
- Frontend real isolado: pré-visualizar, aplicar, consultar e comparar identidade,
  lotes/quantidades, setups e entregas a 390/1440 px. Candidato aplicado: setup
  08:30–09:12:30, produção até 10:13; a outra produção termina às 09:12.
  Os 0,5 minutos são o limite da grelha inteira de início do setup, não um
  intervalo artificial de preparação. Preview: 0,899 s, sem erro de API/página.
  Após reinício, identidade, segmentos, lotes, configuração, score e decisões
  ficaram iguais. Seis páginas privadas passaram também a 390/1440 px.
- O código novo validou em leitura a cópia durável do plano público: revisão
  89, 558 segmentos e 202 lotes, sem violação física, de cobertura ou âncoras.
  Não se substituiu o plano nem se reconstruíram horários de setembro.
- Dez compactações antes/depois na mesma cópia do ISOP, corte de ensaio D14:
  física/cobertura/âncoras, conservação e contrato por encomenda passaram.
  Fingerprint físico idêntico nas 20 execuções. Antes: p50 2,3955 s, p95 2,570 s,
  RSS máximo 121,70 MiB; depois: p50 2,4370 s, p95 2,584 s, 121,64 MiB. São
  medições da compactação, não do recálculo completo nem média de produção;
  não demonstram aceleração. O corte controlado não foi aplicado em produção.

Artefactos: `/tmp/incompolinho-fractional-final-before.xml`,
`/tmp/incompolinho-fractional-focused.xml`,
`/tmp/incompolinho-fractional-browser.json`,
`/tmp/incompolinho-fractional-applied-1440.png`,
`/tmp/incompolinho-fractional-preflight.json`,
`/tmp/incompolinho-fractional-full.xml`,
`/tmp/incompolinho-fractional-real-{before,after}.json`,
`/tmp/incompolinho-fractional-private-release.json`.

### Publicação E Limites Da Prova

- Backup consistente de código/configuração/regras e quatro bases SQLite,
  todas com integridade válida:
  `/home/luis/projects/INCOMPOLINHO-backups/20261002T0205-fractional-resources`.
- Confirmadas ausência de trabalhos/candidatos ativos e operações preparadas,
  revisão e hashes antes de parar e novamente com o backend parado.
- Integrados apenas nove ficheiros de backend, um teste e dois documentos.
  Backend reiniciado em 8010; frontend em 53868 e túnel intocados.
- 274 regressões backend após integração, Ruff e diff-check passaram.
- Primeira verificação pública falhou na página Risco por falha de rede.
  O rastreio seguinte registou `net::ERR_NETWORK_CHANGED` em dez pedidos de
  Configuração, sem erro HTTP/JavaScript. Não se interpretam como um gate verde.
  A repetição sem outros comandos durante o ensaio passou as seis páginas,
  a 390/1440 px, sem falha HTTP, de rede, JavaScript ou escrita.
  Artefactos das tentativas foram conservados:
  `/tmp/incompolinho-fractional-public-release.json`,
  `/tmp/incompolinho-fractional-public-network.json`,
  `/tmp/incompolinho-fractional-public-network-repeat.json`.
- Ponteiro/payload durável ativo, revisão 89, dataset, 558 segmentos físicos,
  202 lotes, configuração, score, mutações e decisões iguais à captura anterior.
  Em 83 segmentos as anotações de intervalos passaram apenas de inteiros para
  decimais integrais (`1036` para `1036.0`); normalizando essa representação,
  nenhuma explicação mudou. Não houve alteração de horários ou quantidades.

A repetição passada não demonstra recuperação automática de falhas de rede,
nem a causa da abertura vazia antiga. Estes permanecem no âmbito da auditoria.
A correção deste bloco não reconstruiu o passado; os prints da antecipação
fracionária pertencem à fixture isolada, não ao plano real de setembro.

## 19. Consultas Que Ficam Em Erro Após Perder A Ligação (02/10)

### Causa E Reprodução

As tentativas públicas da secção 18 revelaram um percurso distinto dos
horários do motor: a página Risco ficava em erro depois de uma consulta
falhar. `frontend/src/api/client.ts`, em `fetchResponse`, fazia apenas um
pedido. Ao receber `TypeError`, publicava "A restabelecer ligação...", mas
não iniciava recuperação. `usePlanQuery` guardava esse erro até mudar a
consulta ou voltar a montar a página. Configuração e outros consumidores
do mesmo cliente partilhavam a falha.

Não se atribui ao backend o `ERR_NETWORK_CHANGED` observado, nem se conclui
que este defeito causou a abertura vazia antiga. O que se reproduziu foi
o comportamento da interface perante uma falha transitória de leitura.

- Criadas duas suítes permanentes antes de editar o cliente: 29 casos,
  dos quais 12 falharam no código anterior e 17 preservaram contratos que
  já funcionavam. Incluem o Risco real com endpoints não substituídos.
- No navegador sobre a árvore anterior e cópia das bases, interromper duas
  consultas Risco deixou a página em erro, apesar de a API voltar a estar
  disponível. Foram dois pedidos e nenhuma repetição; a navegação falhou.
  Artefactos: `/tmp/incompolinho-read-before.json` e
  `/tmp/incompolinho-read-browser-before.json`.

### Correção Delimitada

- Só `GET` recupera erros de rede ou HTTP 502/503/504/524. Há uma tentativa
  inicial e no máximo duas repetições, após 200 e 400 ms.
- O prazo original continua único: 15 segundos por omissão, incluindo
  esperas e leitura dos corpos. Abort e timers são partilhados e limpos;
  cada tentativa não ganha outro orçamento.
- Reutilizam-se os headers capturados de dataset/revisão. HTTP 409, 403,
  validação, identidade divergente e JSON inválido não são repetidos.
- `POST`, `PUT`, `DELETE`, previews e upload continuam com um pedido por
  chamada. Nenhuma perda de resposta provoca repetição automática de escrita.
- Depois de esgotar a recuperação, a mensagem indica falha e pede nova
  tentativa; deixa de anunciar uma ligação a decorrer que não existe.
- O hook de consultas não foi alterado: resultados recuperados de outra
  revisão, componente desmontado ou dataset limpo continuam descartados.
  Sem novos cartões, controlos ou mudanças no algoritmo.

### Provas

- Os 29 testes novos passaram, incluindo timeout durante espera e corpo,
  StrictMode, revisão alterada, desmontagem e ausência de repetição de cinco
  tipos de ação perante rede e HTTP 503.
- Frontend completo: 183 testes (22 Node e 161 Vitest), lint, TypeScript e
  build passaram. Mantém-se o aviso anterior do bundle superior a 500 kB.
- 94 regressões backend de identidade analítica, candidatos, plano vazio
  e transações passaram. O backend não foi editado neste bloco; a última
  corrida integral permanece a da secção 18, não uma corrida nova.
- Navegador privado a 390/1440 px: dez percursos passaram, abrangendo Risco,
  Configuração, Hoje, falha persistente e desmontagem/retorno. Modos Editar
  e Consulta; StrictMode da aplicação ativo. A falha persistente terminou
  após três tentativas por consulta, sem polling infinito. Não houve erros
  JavaScript ou escritas. Dataset, revisão, segmentos, lotes, configuração,
  score, mutações e decisões iguais antes/depois de cada percurso.
- Harness permanente: `scripts/audit_read_recovery.mjs`; bases isoladas em
  `/tmp/incompolinho-read-runtime`, sem aplicar ou recalcular produção.
  Resultados: `/tmp/incompolinho-read-after.json`,
  `/tmp/incompolinho-read-api.xml`,
  `/tmp/incompolinho-read-browser-after.json` e respetivos prints.

### Publicação E Verificação Pública

- Publicado no mesmo link, com backup consistente de código, configuração,
  regras e quatro bases SQLite:
  `/home/luis/projects/INCOMPOLINHO-backups/20261002T003506Z-read-recovery`.
- Antes de integrar, confirmados ausência de trabalhos/candidatos pendentes,
  hashes de toda a árvore e validade física do snapshot ativo. Seis ficheiros
  integrados; apenas `frontend/src/api/client.ts` altera execução da aplicação.
  Backend sem alterações, frontend reiniciado em 53868, túnel conservado.
- Os 183 testes frontend passaram novamente na árvore publicada. Diff-check
  passou. Ponteiro/payload durável ativo, revisão 89, dataset, 558 segmentos,
  202 lotes, configuração, score, mutações e decisões iguais à captura inicial.
- Navegação pública das seis páginas passou a 390/1440 px, sem erros HTTP,
  JavaScript ou escritas. As duas execuções registaram respetivamente quatro
  e seis `ERR_NETWORK_CHANGED` em consultas: não são ensaios sem falhas de
  transporte. Os ecrãs acabaram por carregar.
- O ensaio público completo com falhas injetadas não passou integralmente.
  Risco e Configuração esgotaram tentativas em alguns percursos; noutros a
  página ficou vazia antes de executar a aplicação. O rastreio posterior
  registou `ERR_NETWORK_CHANGED` em módulos React/Shell e no bootstrap Vite,
  não apenas na API. Esses percursos não verificam a recuperação do cliente,
  que ainda não estava carregado. Permanecem como falhas de transporte por
  investigar; não foram apagados, disfarçados como aprovação nem usados para
  aumentar o número de tentativas.
- A repetição pública delimitada ao Risco passou: duas falhas deliberadas,
  recuperação sem recarregar, quatro pedidos no total para os dois efeitos
  de StrictMode, sem falhas inesperadas, JavaScript ou escritas. Print:
  `/tmp/incompolinho-read-public-risk-final-1440-risk_network.png`.

Artefactos públicos: `/tmp/incompolinho-read-public-navigation.json`,
`/tmp/incompolinho-read-public-navigation-repeat.json`,
`/tmp/incompolinho-read-public-recovery.json`,
`/tmp/incompolinho-read-public-recovery-trace.json`,
`/tmp/incompolinho-read-public-risk-final.json`.

Estado: correção das consultas publicada e demonstrada em ambiente isolado
e no percurso público delimitado. A estabilidade de todo o transporte público
continua por demonstrar. Não corrige nem comprova por si só os exemplos
históricos de planeamento e não conclui a auditoria integral.

## 20. Ordenação Da Mesma Referência Podia Trocar Atrasos Individuais (02/10)

Na investigação dos casos nomeados encontrou-se outra falha, independente
dos intervalos históricos: `repair_same_reference_interruptions`, em
`backend/scheduler/priority_normalization.py`, reatribuía os mesmos intervalos
produtivos aos lotes mais urgentes. Validava recursos, quantidades, OTD,
OTD-D e totais de atraso, mas não aplicava o contrato por compromisso usado
pelas restantes propostas de melhoria.

### Reprodução Com Dados Canónicos

Dois lotes da mesma operação, com 125 e 90 peças e um minuto por peça:
o primeiro tinha expedição para subcontratação em D0 e terminava em D3;
o segundo tinha expedição em D1 e terminava em D2. A ordenação proposta
passava os finais para D2 e D3, respetivamente. Assim:

- Atrasos de expedição: 3 + 1 dias passavam a 2 + 2 dias.
- Ambos os planos eram fisicamente válidos e conservavam todas as peças,
  durações, intervalos ocupados e o setup de 30 minutos.
- OTD e OTD-D mantinham-se em 100%; os dois pedidos de cliente eram servidos
  no prazo. O total de atrasos de expedição mantinha-se em quatro dias.
- Contudo, o segundo lote ganhava mais um dia de atraso. O contrato comum
  recusava o resultado, mas esta rotina aceitava-o antes desse contrato.

As oito variantes iniciais falharam no código anterior: referências normais
e gémeas, identificadores originais e renomeados, inputs em ambas as ordens.
Há catálogo de operações, cadência/OEE, procura por cliente e validação
canónica; não se substituíram scores ou validadores para provocar a falha.

### Correção E Verificação

- A rotina passa a chamar `contract_verdict` antes de aceitar cada alteração.
  Totais iguais ou melhores deixam de compensar a perda de um compromisso.
  Não muda prioridades, regras industriais, dimensionamento ou IDs.
- Acrescentados checkpoints durante construção e reatribuição dos blocos,
  para respeitar o deadline e cancelamento já existentes.
- `tests/test_same_reference_no_loss.py`: doze regressões permanentes. As oito
  reproduções anteriores passam; dois casos interrompem dentro da rotina
  sem alterar inputs. Dois casos percorrem o normalizador comum e demonstram
  que ele continua a antecipar ambos os lotes para D0, com o único setup
  original, sem perdas, e atinge um resultado idempotente.
- Backend completo: 2075 passaram, dois ignorados, em 425,11 s. Esta corrida
  incluía as oito primeiras regressões; os quatro testes suplementares
  foram depois incluídos nos 95 testes focados finais, todos aprovados.
  Ruff passou. Avisos de limpeza de temporários pytest e de TestClient
  não são falhas da aplicação e ficaram registados no output.
- Frontend: 183 testes passaram; ESLint, TypeScript e build passaram.
  O aviso de bundle superior a 500 kB permanece. A primeira tentativa de
  copiar dependências desfazia symlinks pnpm e falhou na resolução de módulos;
  foi substituída por uma cópia que conserva esses links, sem editar dependências
  da aplicação pública. As verificações finais usaram essa cópia independente.
- Navegador privado: seis páginas, a 390/1440 px, sem falhas HTTP, de rede,
  JavaScript ou escritas; revisão 89, dataset, segmentos, lotes, configuração,
  indicadores, mutações e decisões iguais antes/depois. Artefactos:
  `/tmp/incompolinho-named-private-navigation.json` e `-network.json`.
- Uma compactação retrospectiva, apenas na cópia SQLite, passou física,
  âncora, conservação e contrato em 11,256 s. A pesquisa de dez segundos
  terminou como `partial/budget`, não como prova de ótimo. Não é um benchmark
  p50/p95 nem conclui o fecho dos casos nomeados.

### Limite Do Resultado

O plano público observado continua na revisão 89. O lote inicial BFP082
começa em D4, 09:49; BFP112 começa em D4, 12:20. A sequência BFP079 atual
usa PRM031 de D4 a D12 e PRM039 no lote com início em D14: não se deve
atribuir uma explicação da imagem antiga de 24/09 a estes horários diferentes.
VUL195 e VUL174 continuam em D11. Estes são dados do snapshot, não provas
de que todas as posições sejam inevitáveis ou ótimas.

Esta correção elimina a troca de atrasos reproduzida. Não reconstrói os
horários históricos, não retira a âncora BFP083 e não demonstra que todas
as referências referidas pelo utilizador já estão na melhor posição.

### Publicação Verificada

Quatro ficheiros integrados depois de verificar hashes da árvore inteira,
ausência de trabalhos/candidatos ativos e validade do plano persistido.
O backend foi parado brevemente para backup consistente de código,
configuração, regras e quatro bases SQLite, todas com integridade aprovada:
`INCOMPOLINHO-backups/20261002T012450Z-same-reference-no-loss`.
Backend reiniciado em 8010; frontend e túnel conservados, no mesmo link.

Os 95 testes focados passaram novamente na árvore publicada, tal como Ruff
e diff-check. O teste da base real, ignorado na corrida integral por não
existir uma base na cópia inicial, passou depois sobre a cópia SQLite.
Ponteiro e payload ativo persistido, revisão 89, dataset e os oito campos
de estado da API ficaram exatamente iguais à captura anterior à integração.

Navegação pública das seis páginas a 390/1440 px passou, sem erros HTTP,
JavaScript ou escritas. O rastreio registou duas consultas stock com
`ERR_NETWORK_CHANGED`: os ecrãs carregaram, mas não se classifica o ensaio
como transporte limpo. Artefactos: `/tmp/incompolinho-named-public-navigation.json`,
`-network.json` e prints; o print de Plano a 1440 px foi inspecionado.
Esta publicação não reescreve setembro e não conclui os casos nomeados
ou a estabilidade de toda a ligação pública.

## 21. Rotação Incompleta Da Campanha Urgente E Proteção Por Data (02/10)

### Causa Reproduzida No Snapshot Real

A análise usou uma cópia SQLite aberta só para leitura do snapshot ativo
`56efe888a6de4808a799ad6353fdcdc9`, revisão 89. O payload tem SHA256
`b194df17573508aa87c84ebb01b644dc0afb83d48b2705ab700d8de512d75f81`.
No estado observado, BFP080 começa antes de BFP082. Esta última tem dois
runs adjacentes da mesma afinação: o lote urgente e uma continuação sem setup,
com outro `run_id`. A rotação anterior levava apenas o run urgente para
antes de BFP080; deixava a continuação para depois de BFP080.

Isso exigia reinstalar BFP082 para continuar a mesma campanha. A validação
completa recusava corretamente `missing_tool_change_setup`: faltavam os
75 minutos de preparação. O defeito estava na geração da proposta, não na
validação nem numa falta de prioridade configurável para esta referência.
Uma alternativa conservadora existia: mover a campanha completa, incluindo
a continuação, antes de BFP080, sem acrescentar montagens.

Encontraram-se duas divergências adicionais nesse percurso:

- A reconstrução repunha o setup nominal na continuação e materializava a
  rotação numa escala comprimida de minutos produtivos. Um setup podia
  começar perto do fecho e ultrapassar o turno, sendo depois recusado por
  `outside_shift`, capacidade diária ou preparação desligada. Não bastava
  retirar a faixa visual: era necessário alocar fisicamente com o calendário.
- Reparação de prioridades, auditoria e troca de capacidade inferiam proteção
  histórica pela data de calendário. Um candidato novo, ainda não executado,
  podia ser tratado como histórico e deixar de ser reparado ou auditado.
  A proteção real já é estabelecida pelo coordenador do plano ativo, por lote
  inteiro; repetir essa inferência dentro de reparações não distingue os
  inputs de construção nova dos inputs de replaneamento.

### Correção Delimitada

- A rotação transporta as continuações imediatamente adjacentes, sem setup,
  com a mesma identidade física de afinação. Outra afinação ou um setup
  explícito termina esse conjunto; não se fundem referências só pelo nome
  da ferramenta. Entre runs reconstruídos da mesma afinação conserva-se
  montagem, em vez de repor o setup nominal.
- A alocação usa `_schedule_preemptive_run` com os bloqueios do resto do
  plano, através de `_with_plan_resource_blocks`. São os mesmos calendários,
  operadores, equipas de setup e restrições do alocador existente. Mantêm-se
  IDs, quantidades e durações exatas; física, conservação e contrato por
  compromisso continuam obrigatórios antes da aceitação.
- `backend/scheduler/protection.py` centraliza provas históricas, âncoras e
  IDs protegidos pelo chamador. Rotação e reparação da mesma referência
  respeitam todos os membros protegidos, incluindo continuações. Auditoria
  distingue bloqueio histórico de decisão manual. O corte histórico em
  `backend/plans/frozen.py` não foi alterado.
- Não existem exceções para BFP082/BFP080 nem alterações da hierarquia de
  objetivos. Cancelamento e deadline continuam nos checkpoints existentes.

### Provas E Limites

- Antes da correção: 27 falhas em 34 testes novos. A reprodução adicional de
  setup no fecho também falhou antes de substituir a materialização crua.
  Depois: 95 regressões focadas passaram, mais 73 do controlo de timeout,
  auditoria e novas reproduções. Variantes normais/gémeas, identificadores
  diferentes, ordem invertida, afinações distintas e proteção por prova ou
  âncora demonstram que a correção não depende da referência.
- A primeira regressão integral teve 2113 aprovações, dois testes ignorados
  e uma falha: um mock do teste de timeout não aceitava o novo argumento
  de proteção. A assinatura foi compatibilizada sem reduzir a asserção.
  A regressão integral final passou: 2115 aprovações e um teste ignorado,
  em 423,41 s, incluindo a base real copiada. O teste ignorado é opt-in;
  permanece um aviso de depreciação do TestClient.
- Dez normalizações retrospectivas sobre a cópia real deram o mesmo resultado,
  sem alterar a origem nem a âncora BFP083: p50 5,097 s e p95 5,740 s.
  Estes tempos medem somente essa fase, não o pedido completo, nem provam
  fecho de todas as alternativas ou um ótimo global. Mantêm-se rejeições de
  propostas tentativas de junção de setup por `outside_shift`; não entraram
  no candidato aceite e permanecem um limite da pesquisa por estudar.
- Nesse ensaio, BFP082 urgente passa de D4 09:49 para D0 09:15, na PRM019.
  A continuação permanece na mesma campanha. BFP080 desloca-se mas continua
  antes do prazo D8. VUL195/VUL174 passam de D11 para D8 na PRM039.
  Física, quantidade, compromissos individuais e número/minutos de setups
  passaram; os 195 setups e 9075 minutos totais não aumentaram.
- Frontend: 183 testes, lint, TypeScript/build passaram; aviso de bundle
  superior a 500 kB permanece. Navegador isolado verificou BFP082 em D0
  às 09:15 a 390/1440 px, sem falhas de rede/HTTP/JavaScript ou escritas.
  As seis páginas reais também carregaram nos dois tamanhos. Prints:
  `/tmp/incompolinho-realcase-bfp082-1440.png` e `-390.png`.
- `scripts/audit_realcase_normalization.py` torna o ensaio repetível e abre
  a base explicitamente em modo só de leitura. `--retrospective` retira provas
  de execução apenas dos inputs destacados; mantém as âncoras. Não dispõe
  de escritor de produção. Relatórios: `/tmp/incompolinho-realcase-before.xml`,
  `-closed.xml`, `-control-final.xml`, `-full-final.xml`, `-repetitions.json`,
  `-browser.json` e `-private-navigation.json`.

### Publicação E Verificação

Publicado no mesmo link após backup consistente de código, configuração,
regras e quatro bases SQLite com integridade aprovada:
`INCOMPOLINHO-backups/20261002T021627Z-campaign-rotation`.
Treze ficheiros integrados, após validar física e conservação do snapshot
ativo e conferir hashes de toda a árvore. Backend reiniciado em 8010;
frontend, porta 53868 e túnel conservados.

Na árvore publicada, 144 regressões passaram, incluindo proteção histórica,
controlo do deadline e reparações afetadas. Ruff passou. Ponteiro e payload
durável, dataset, revisão 89 e os oito campos de estado da API mantiveram-se
iguais à captura inicial. Não foram gravados candidatos retrospectivos.
As seis páginas públicas abriram a 390/1440 px, sem erros HTTP, JavaScript,
escritas ou falhas de rede nesta execução. Artefactos:
`/tmp/incompolinho-realcase-public-focused.xml`, `-public-navigation.json`,
`-public-navigation-network.json` e prints. Isto não prova estabilidade
permanente da ligação nem explica as falhas de transporte anteriores.

Estado: correção publicada e prova retrospectiva isolada concluída.
O print de BFP082 em D0 demonstra o candidato ensaiado, não uma substituição
do plano público. O print público mantém os horários anteriores, como previsto.
Os horários históricos continuam protegidos. É necessário esclarecer se
setembro representa simulação ou execução efetiva antes de reconstruí-los.
BFP112 já começa em D4 no snapshot observado; a troca BFP079 da imagem antiga
não corresponde à sequência atual. Esses exemplos e a auditoria integral
não ficam concluídos por esta correção.

## 22. Cache De Transferências Ignorava Recursos Partilhados

### Causa E Reprodução

`transfer_consolidation._resource_signature` identificava apenas as duas
máquinas da transferência e a ferramenta. O alocador depende também dos
operadores do grupo, equipas de setup, calendários e inputs canónicos. Depois
de outra máquina libertar esses recursos, a mesma execução podia reutilizar
uma hipótese recusada, apesar de uma execução nova encontrar a solução.
Uma melhoria encadeada podia, assim, terminar falsamente como concluída.

Dezassete regressões em `tests/test_transfer_cache_invalidation.py` usam o
alocador real: libertação noutra máquina, operadores, equipas de setup,
alteração de grupo, remoção de ausência, nomes e ordem diferentes, reutilização
legítima, identidade de campanha, precisão fracionária e duas cadeias no
coordenador. O módulo antigo falhou dezasseis desses
testes; passou somente a reutilização com inputs efetivamente inalterados.

### Correção E Âmbito

A cache continua limitada à execução. A sua identidade passa a incluir o
campos exatos dos segmentos, lotes, fingerprints de dados/configuração, modelo e
limites da pesquisa. Qualquer alteração invalida as conclusões anteriores;
conserva-se só o contexto corrente. Inputs idênticos continuam reutilizáveis.
Anotações de diagnóstico e ordem de segmentos não alteram a identidade da cache.
Não se alteraram preferências, alocação, limites de aprovação ou proteção.

A revisão final encontrou duas omissões na primeira correção: a assinatura
física arredonda tempos a três casas e não inclui `run_id`/metadados de
campanha, usados por `_resolve_runs`. Duas novas regressões falharam nessa
versão intermédia. A cache usa agora todos os campos do segmento sem
arredondamentos; só exclui `left_shift_blockers`, que é diagnóstico.

Esta prova elimina a dependência incompleta da cache; não atribui, sem
reprodução, a mesma causa à antiga fotografia de BFP079 em 24/09. Os horários
de produção anteriores continuam protegidos e não foram substituídos.

### Validação

As 112 regressões focadas passaram. Frontend: 183 testes, lint e
TypeScript/build passaram. Mantém-se o aviso de bundle superior a 500 kB.
Primeira regressão integral: 2130 testes passaram, um ignorado, em 480,54 s,
incluindo a cópia da base real. O caso opt-in de latência HTTP durante 151 s
de cálculo simulado passou isoladamente em 152,63 s. Não mede a velocidade
do solver real. A regressão integral da versão final exata passou: 2132 testes,
um ignorado, em 550,54 s, incluindo a cópia da base real.
Mantém-se o aviso de depreciação do TestClient.

O frontend real retirou duas ausências Grandes A/B, pré-visualizou sem
alterar o plano ativo, aplicou e conservou exatamente segmentos, lotes,
configuração e dados do candidato persistido. Os dois lotes da ferramenta
ficaram na M2, sem transferência: não se impôs uma preferência pela M1.
Reload e reinício conservaram oito campos da API e o ponteiro/payload durável.
As seis páginas privadas abriram a 390/1440 px, sem escritas ou erros HTTP/JS
e sem falhas de rede. O percurso de aplicação teve quatro GET cancelados no
remount de StrictMode; foram registados e cada URL teve resposta 200 posterior.
Artefactos: `/tmp/incompolinho-transfer-browser.json`, `-restart.json`,
`-private-navigation.json` e `-private-navigation-network.json`.
A prova do navegador verifica o percurso e o candidato exato; a reprodução
da invalidação durante uma melhoria encadeada pertence aos testes permanentes.
O percurso de aplicação, reinício e navegação foi repetido com a versão exata.
Prints dessa instância isolada: `/tmp/incompolinho-transfer-confirmacao-1440.png`
e `-390.png`. Publicação confirmada abaixo.

Dez execuções anteriores e dez corrigidas, sobre cópia SQLite consistente,
passaram física, quantidade, âncora, contrato por compromisso e imutabilidade.
Na repetição sem suites funcionais concorrentes, a fase de libertação de
capacidade teve p50/p95 de 11,054/11,448 s antes e 10,929/11,209 s depois;
VmHWM máximo 128,4/129,7 MiB. São medições locais dessa fase, não o tempo médio
da API nem uma afirmação de ganho significativo de velocidade. O primeiro
contador de RSS herdava o processo lançador; foi descartado e os ensaios
repetidos com `/proc/self/status`.
Os dez ensaios finais foram repetidos após a correção de precisão/campanha;
o baseline anterior foi conservado com os mesmos hashes de código e dados.
As vinte pesquisas terminaram `partial/budget`: um candidato no baseline,
dois depois, com 14 ou 10 transferências e sem perda individual de serviço.
não se afirma determinismo, fecho global ou eliminação de todas as trocas.
Relatórios: `/tmp/incompolinho-transfer-baseline.xml`, `-focused.xml`,
`-benchmark.json` e testes permanentes na árvore isolada.

O ensaio do frontend encontrou outra lacuna a verificar: reconstruir o gate
em `replan/jobs.py` pode perder o resumo `improvement_report` do percurso de
libertação de capacidade. A validação desta cache não encerra essa auditoria
de transporte nem a matriz de percursos do plano integral.

### Publicação

Publicado no mesmo link após backup consistente de código, configuração,
regras e bases SQLite: `INCOMPOLINHO-backups/20261002T032851Z-transfer-cache`.
Quatro ficheiros integrados com `apply_patch`, após conferir hashes de toda
a árvore e a ausência de trabalhos/escritas pendentes. Backend reiniciado
em 8010; frontend, porta 53868 e túnel conservados.

Na árvore publicada, 112 regressões passaram e Ruff/diff --check passaram.
Os seis ecrãs públicos abriram a 390/1440 px sem erros HTTP/JS, escritas
ou falhas de rede registadas. Snapshot ativo, payload, revisão 89, dataset,
regras e oito campos da API conservados exatamente. Artefactos:
`/tmp/incompolinho-transfer-public-focused.xml`, `-public-navigation.json`
e `-public-navigation-network.json`. Serviços privados de teste encerrados.

Estado: bloco publicado e verificado, não auditoria integral concluída.
Os prints são da aplicação de teste isolada, não de uma reconstrução do
plano histórico público. Não se declara que todas as transferências são
inevitáveis, que a pesquisa parcial é ótima ou que a fotografia antiga de
BFP079 foi explicada por este defeito.

## 23. Relatório Perdido Entre Cálculo, Aplicação E Reinício

### Causa Reproduzida

O coordenador devolvia `ScheduleResult.improvement_report`, mas os restantes
percursos não transportavam esse campo de forma completa:

- `replan/jobs.py` reconstruía o gate depois da robustez, apagando o resumo
  informativo da compactação após libertar capacidade. A aplicação voltava
  a reconstruí-lo e perdia novamente esse resumo.
- `serialize.py` não guardava nem restaurava o relatório completo. O campo
  também faltava em `CopilotState`, nas capturas para reversão e nas conversões
  entre simulador, movimento manual, candidato e estado ativo.
- Depois de reparar uma alocação ou adotar outra configuração, o estado de
  verificação anterior podia continuar a ser apresentado como atual.

Onze regressões iniciais: dez falharam no código anterior e uma passou.
O teste do trabalho executa a compactação real e esgota apenas o orçamento
da fase de melhoria de teste; não substitui a validação física ou o solver
por um resultado inventado. Confirmou `partial/budget` no cálculo e ausência
do resumo no trabalho pronto.

### Correção Delimitada

O campo completo é conservado em estado, snapshots, simulador e movimento
manual, incluindo aplicação, reversão e recuperação. O fecho do replaneamento
e do restauro reanexa o resumo com o candidato final, sem pesquisar ou alterar
o plano. Uma assinatura física diferente invalida a verificação anterior;
adotar inputs diferentes num restauro ou reutilizar um baseline com outra
configuração apresenta `not_evaluated/inputs_changed`.

O campo opcional entra no fingerprint dos novos snapshots. Snapshots v4
anteriores sem o campo conservam o cálculo original do hash e continuam
legíveis; a ausência de relatório não é interpretada como pesquisa concluída.
Tipos e respostas são aditivos. Não mudaram regras, preferências, aprovações,
horas, lotes ou a interface existente.

### Provas Da Versão Isolada

- 14 regressões novas de transporte; reforçada a regressão da pré-visualização
  manual em background para exigir o relatório exato aplicado e persistido.
- 70 regressões de contrato passaram; suíte completa: **2146 passaram,
  um opt-in ignorado**, em 462,29 s. O teste ignorado de HTTP com cálculo
  simulado de 151 s foi verificado separadamente na secção 22; não voltou
  a ser executado neste bloco.
- Frontend: **183 testes**, lint, TypeScript/build e Ruff passaram.
  Permanece o aviso existente de bundle superior a 500 kB.
- Navegador real: remoção de ausências, pré-visualização, aplicação e reinício
  passaram. O percurso normal terminou `completed`, com três melhorias;
  o ensaio controlado de orçamento zero terminou `partial/budget` e mostrou
  "melhoria parcialmente verificada" no ecrã existente. Ambos aplicaram
  exatamente os segmentos, lotes, configuração, dados e relatório apresentados.
- Pré-visualização/aplicação a 1440 px; consultas e capturas a 390/1440 px.
  Os dois reinícios conservaram os nove campos conferidos na API e o ponteiro
  e payload duráveis. Seis páginas passaram nos dois ambientes privados, sem
  erros JS/HTTP, escritas de auditoria ou falhas de rede registadas.
  Durante os percursos de aplicação, quatro GET cancelados por StrictMode em
  cada ensaio tiveram resposta 200 posterior; as restantes falhas foram zero.

Artefactos: `/tmp/incompolinho-report-{before,contract,full}.xml`,
`-browser.json`, `-partial-browser.json`, `-restart.json`,
`-partial-restart.json`, `-private-navigation.json`,
`-partial-navigation.json` e os respetivos prints/rastreios.

### Custo Da Gravação

Dez repetições de serialização e desserialização, sem recalcular o plano:
na cópia real com 558 segmentos, p50/p95 passaram de 148,10/170,35 ms para
156,80/192,53 ms; no candidato real de teste, de 2,13/2,17 ms para
2,31/2,95 ms. Pico de memória: 117,53/117,50 MiB. O novo snapshot do candidato
tem mais 1388 bytes, conservando agora o relatório que o anterior perdia.
A representação de entrada do leitor antigo foi adaptada apenas em memória
para esse benchmark; as duas bases de origem ficaram intactas. Não se infere
ganho de velocidade nem média de produção destes ensaios.

### Publicação E Verificação Final

Publicado no mesmo link após o backup consistente
`INCOMPOLINHO-backups/20261002T040638Z-report-transport`. Dezasseis ficheiros
integrados com `apply_patch`, com guarda de hashes de toda a árvore, ausência
de trabalhos ativos e confirmação do snapshot durável. Backend/frontend
parados durante a integração e retomados nas mesmas portas 8010/53868;
túnel conservado. Uma consulta de guarda iniciada antes da paragem tentou
concluir durante a manutenção e teve ligação recusada; a guarda durável
sem serviços e a guarda completa depois do reinício passaram.

Na árvore publicada, **221 regressões passaram**, Ruff e `git diff --check`
passaram. Seis páginas públicas passaram a 390/1440 px, sem erros JS/HTTP,
escritas ou falhas de rede registadas. A API conservou os oito campos
conferidos, incluindo revisão 89, dataset, plano, configuração e decisões;
ponteiro ativo, payload durável e regras também ficaram exatamente iguais.
Artefactos: `/tmp/incompolinho-report-public-focused.xml`,
`-public-navigation.json` e `-public-navigation-network.json`. Serviços
privados encerrados; serviços públicos ativos.

Estado: este bloco foi publicado e verificado. Não reconstrói setembro e
não conclui a matriz integral de melhorias, desempenho ou concorrência.

## 24. Candidatos Com Origem Incompleta E Recuperação Do Movimento

### Causa Reproduzida

Uma revisão igual não garantia que o contexto fosse igual. A identidade comum
não incluía versões do modelo, política, contrato de melhoria e robustez, nem
decisões manuais. Reutilizava ainda o fingerprint de comparação de entregas,
que omite máquinas não referenciadas e não serve para uma origem exata.

Os movimentos em background verificavam apenas dataset, revisão e parte dos
inputs: mudanças de regras, horário, decisões e overlays podiam não invalidar
o resultado. Replaneamentos admitiam explicitamente uma origem `legacy` sem
comparar o contexto completo. A cache de pré-visualizações conservava objetos
mutáveis do produtor; o hash do CTP cobria apenas a alocação, não a procura
mutada e o candidato executável completo.

No frontend, após conflito de aplicação, o modal mantinha a revisão antiga.
Uma nova verificação válida podia ficar indisponível para aplicar. Não era
falta física de capacidade; era recuperação incompleta do contexto do ecrã.

Quinze testes iniciais falharam no código anterior: catorze reproduziram falhas
de comportamento, um apenas tinha uma expectativa de texto demasiado restrita.
O replaneamento já rejeitava a mudança de `MODEL_VERSION`; foi conservada essa
proteção e alargada aos restantes contratos. Não se atribuem as fotografias
históricas a estas falhas sem uma reprodução específica.

### Correção Delimitada

- Uma origem comum inclui dataset, revisão, configuração, todos os recursos,
  plano, mutações, regras, decisões manuais e versões dos contratos.
- Snapshots novos guardam essa origem, protegida pelo fingerprint do payload.
  Snapshots antigos sem o campo continuam legíveis; candidatos incompletos
  exigem nova pré-visualização. Não foi alterada a referência do plano ativo.
- Caches separam o resultado do objeto do produtor e verificam o conteúdo
  executável completo antes da aplicação. O CTP inclui a simulação associada.
- Movimentos capturam uma cópia coerente sob o coordenador, verificam a mesma
  origem e devolvem uma cópia do candidato, sem recalcular na aplicação.
- O modal descarta apenas a comparação obsoleta, atualiza o snapshot e mantém
  máquina, dia, hora e motivo. Não repete a escrita; recusas de aprovação não
  são confundidas com conflitos de revisão.

Não mudaram preferências industriais, loteamento, permissões ou interface.
Não se adicionaram cartões, nem se alteraram automaticamente os horários públicos.

### Verificação Isolada

- Vinte regressões novas: identidades, cache mutável, modelos, regras, decisões,
  recursos não referenciados, aplicação exata e consulta sem alteração do estado.
- Suíte backend completa: **2165 passaram, um opt-in ignorado**, em 436,59 s.
  O vigésimo teste, acrescentado depois dessa execução para verificar a projeção
  de leitura, passou com os outros dezanove em 6,59 s. Ruff passou.
- Frontend: **185 testes**, lint e TypeScript/build passaram. Permanece o aviso
  existente de bundle superior a 500 kB. Usaram-se scripts npm sobre dependências
  existentes, porque pnpm/corepack não estavam utilizáveis neste ambiente.
- Navegador real, instância privada: duas sessões verificaram o mesmo lote;
  uma aplicou e a outra recebeu 409 sem alterar o estado. A segunda preservou
  o pedido, atualizou a revisão, verificou novamente e aplicou a 390 px.
  Foram duas aplicações válidas e uma recusa, sem repetição automática.
- O reinício conservou nove campos da API, incluindo relatório de melhoria,
  ponteiro ativo e payload durável. Seis páginas passaram a 390/1440 px, sem
  erros JS/HTTP ou escritas de auditoria. Fixture genérica de novembro, não
  reconstrução das fotografias de setembro.

Uma comparação inicial do browser falhou porque comparava anotações de leitura
com o snapshot bruto. `plan_view_explanations` recalcula numa cópia três campos
explicativos: `left_shift_blockers`, `material_release_day` e
`release_delay_workdays`. O ensaio final exige igualdade integral entre snapshot
e `/segments`, igualdade física com `/plan-view` e estabilidade das leituras;
a regressão permanente exige também que a consulta não altere estado ou base.

Dez medições na cópia real com 558 segmentos, sem solver: identidade p50/p95
37,64/54,63 ms antes e 35,59/53,08 ms depois; serialização completa
87,80/107,33 ms antes e 138,18/146,91 ms depois. A proteção adicional aumenta
o custo da gravação; estes valores não demonstram ganho de velocidade nem
constituem média de produção. A base de origem ficou intacta.

Artefactos: `/tmp/incompolinho-identity-browser.json`, `-restart.json`,
`-private-navigation.json`, `-benchmark-{before,after}.json` e prints associados.

### Pendências Não Confundidas Com Este Bloco

No ensaio exploratório, pedir a um lote inicial para permanecer exatamente no
seu início atual devolveu verificação inconclusiva, apesar de o plano existente
ser uma testemunha. Esse percurso de movimento sem alteração requer reprodução
e correção próprias; não foi convertido em impossibilidade física nem considerado
resolvido aqui. Também permanecem os cenários reais, fecho de pesquisa, lifecycle
completo e medições globais da matriz anterior.

Estado: bloco validado na cópia isolada; publicação e verificação pública
registadas abaixo apenas depois de concluídas.

### Publicação E Guarda Final

Publicado no mesmo link em 02/10/2026, após backup consistente
`INCOMPOLINHO-backups/20261002T045246Z-candidate-identity`. Treze ficheiros
integrados com `apply_patch`, com guarda da árvore completa e das bases.
Backend parado e frontend temporariamente suspenso durante a integração;
serviços retomados nas mesmas portas 8010/53868, sem alterar o túnel.

Na árvore publicada: **297 regressões backend** e **185 testes frontend**
passaram; Ruff, lint, TypeScript/build e `git diff --check` passaram.
Seis páginas públicas a 390/1440 px passaram em leitura, sem erros JS/HTTP
ou escritas. Guarda confirmou revisão 89, dataset, 558 segmentos, 202 lotes,
configuração, indicadores e decisões iguais; ponteiro ativo, payload durável
e regras intactos. Validação física da cópia recente do plano também passou.

Artefactos finais: `/tmp/incompolinho-identity-public-focused.xml`,
`-public-navigation.json` e respetivos prints. Serviços privados encerrados;
serviços públicos ativos. Este bloco está publicado; as pendências acima
continuam abertas e não se afirma que o plano atual seja ótimo.

## 25. Alocação Dos Lotes Existentes E Preparação Protegida (02/10/2026)

### Causas Demonstradas

O movimento começava pelo otimizador de procura, que podia gerar novos lotes.
A comparação posterior exigia as identidades e quantidades originais e rejeitava
esse resultado. Não era uma prova de falta de capacidade. Mesmo manter o início
atual podia falhar: a reparação da campanha de origem procurava recolocar setup
antes de conhecer a nova posição do lote que já continha essa preparação.

Uma segunda falha foi reproduzida no navegador: a melhoria trabalhava sobre
o resíduo, sem os lotes protegidos. Estes eram reunidos apenas para avaliar
o resultado. A compactação não via a ferramenta montada no prefixo protegido,
conservando preparação redundante e tempo improdutivo. Ocultar a faixa não
eliminava essa causa física. A hora por omissão também podia vir de um fragmento
só de setup, em vez do primeiro início produtivo do lote inteiro.

### Correção E Limites

- `manual_move.py` tenta primeiro o pedido com posições restantes fixas;
  a reorganização usa `create_tool_runs` e `solve_global_jit` sobre os lotes
  originais. Sem novo dimensionamento, IDs, quantidades ou obrigações de entrega.
- A nova posição participa na prova de montagem retida antes da reparação
  do setup de origem. Uma interrupção física real continua a exigir preparação.
- `improvement.py` compacta a sequência completa, incluindo o prefixo protegido,
  e verifica que nenhum desses segmentos mudou antes de extrair o resíduo.
  Setup redundante liberta tempo real; operadores e calendários são revalidados.
- O solver recebe o limite do horizonte do movimento em todas as suas vias.
  O horizonte normal do planeamento automático não foi alterado.
- Backend e modal usam o primeiro início produtivo; o pedido explícito prevalece.
  Versões da alocação e do contexto protegido integram a identidade do candidato.
- Permanecem o orçamento único de 60 s, a reserva de fecho, cancelamento,
  histórico e decisões manuais protegidos, validação de cobertura e aplicação
  do candidato exato. Pesquisa limitada continua a ser inconclusiva, não impossível.

Sem exceções para referências, novas preferências industriais ou novos cartões.
Esta correção não demonstra que todas as produções históricas de setembro
possam ser antecipadas, nem que todas as transferências restantes sejam necessárias.

### Regressões E Navegador

Nove regressões novas cobrem montagem retida, início atual, antecipação da
continuação, IDs e quantidades, reorganização, setup isolado e prefixo protegido;
duas verificam invalidação por versão. Três casos frontend verificam a hora
produtiva. Testes antigos que simulavam o otimizador foram adaptados à alocação,
mantendo as recusas de resultados incompletos, renomeados ou fora do horizonte.

Suíte backend final: **2176 passaram, 2 ignorados**, em 423,52 s. Um teste é
opt-in de responsividade; outro requer a base real, não copiada para a suíte.
Frontend: **188 passaram** (22 node, 166 Vitest); lint, TypeScript/build e Ruff
passaram. Permanece o aviso preexistente de bundle superior a 500 kB.

Frontend real privado, 390/1440 px: manter início, deslocar o cabeça de campanha
e mudar máquina foram verificados e aplicados. Um ensaio adicional começou com
uma colisão no horário pedido e reorganizou efetivamente outros lotes. Quatro
lotes de 100 peças conservados, início exato, gates físicos e de cobertura
válidos, aplicação igual à pré-visualização, sem erros JS/HTTP. O reinício
preservou nove campos da API e o estado durável. Seis páginas passaram em leitura.
São fixtures genéricas futuras de novembro, não fotografias do caso real de setembro.

### Medição Na Cópia Real

Dez repetições antes/depois do mesmo pedido para manter
`LOT_BFP082_PRM019_1092262X100_22` no D15 às 14:50, na PRM019:
p50/p95 **25,736/27,040 s** antes e **2,899/2,978 s** depois; pico RSS
159,18/125,39 MiB. Nos vinte cálculos, gates físicos, cobertura, obrigações
e imutabilidade da origem passaram; não houve aplicação na produção.

Não são resultados equivalentes nem uma média de produção: a versão anterior
reorganizava globalmente antes de aceitar o pedido e encontrou 7-11 melhorias
adicionais; a nova parte da testemunha válida e encerrou a melhoria limitada
com zero movimentos adicionais. Ambas reportam pesquisa parcial, sem promessa
de ótimo. A nova versão repetiu a mesma assinatura física nas dez execuções.
Esta medição não valida a prioridade inicial da BFP082 no D0.

Artefactos: `/tmp/incompolinho-allocation-full-final.xml`,
`-browser.json`, `-global-browser.json`, `-restart.json`,
`-private-navigation.json`, `-real-{before,after}.json` e prints associados.

Estado: bloco validado isoladamente. Publicação e guarda final serão registadas
apenas depois de concluídas; casos históricos e auditoria integral permanecem abertos.

### Publicação E Verificação Pública

Publicado no mesmo link em 02/10/2026, após backup consistente
`INCOMPOLINHO-backups/20261002T055324Z-original-lot-allocation`.
Treze ficheiros integrados com guarda da árvore completa; backend parado e
frontend suspenso brevemente, retomados nas mesmas portas e túnel.

Na árvore publicada, **243 regressões backend e 188 testes frontend** passaram.
Ruff, lint, TypeScript/build e diff-check passaram. O ensaio de consolidação
sobre a base real passou em leitura. Seis páginas públicas a 390/1440 px
passaram sem erros JS/HTTP ou escritas; revisão 89, dataset, 558 segmentos,
202 lotes, configuração, indicadores, decisões, regras, ponteiro e payload
durável ficaram iguais. A validação física prévia do plano ativo passou.

Artefactos finais: `/tmp/incompolinho-allocation-public-focused.xml`,
`-public-navigation.json` e prints. Serviços privados encerrados; públicos
ativos. Não se recalculou nem substituiu o plano público e não se declara
resolvida a matriz histórica de inícios, prioridades e transferências.

## 26. Fecho Canónico Que Descartava Antecipações Válidas (02/10/2026)

### Causa Reproduzida

O contexto completo introduzido no bloco anterior não bastava: o normalizador
recebia os lotes protegidos, mas não os transmitia a todos os seus passos.
`_merge_detached_setup_segments` juntava preparação e produção protegidas;
`_start_production_at_open_after_parked_setup` podia deslocar trabalho fixo.
Ao antecipar outro lote, `apply_partial_gap_move` dividia e juntava novamente
o plano completo, perdendo a proteção explícita. A divisão considerava provas
históricas, mas não as decisões manuais. A reparação de campanhas interrompidas
também não recebia as proteções adicionais.

Consequência demonstrada: um lote livre na M2 permanecia no D2 apesar de poder
começar no D0. A proposta antecipava-o, mas alterava os dois fragmentos fixos
de outro lote na M1; a verificação final de preservação descartava-a integralmente.
O mesmo sucedeu com identificadores diferentes. Não era falta de capacidade
nem uma preferência industrial necessária.

Outro defeito: anexar uma preparação à produção no início de turno deslocava
a sequência seguinte, sem voltar a dividir os segmentos no limite dos turnos.
A validação detetava `outside_shift` e revertia uma reparação que poderia ser
fisicamente válida. Um teste antigo esperava precisamente esse bloco indevido
entre 13:33 e 19:06 no turno A; agora exige fragmentos A/B com trabalho e
quantidade conservados.

### Correção E Provas

- Os passos de fecho usam a mesma identidade de lotes protegidos: provas,
  decisões manuais e conjunto explícito. Movimentos parciais não deslocam
  fontes protegidas nem alteram o setup que prepara trabalho fixo.
- A proteção acompanha os lotes em todos os sublotes de validação recursiva.
  Campanhas interrompidas não deslocam membros ou bloqueadores protegidos.
- A junção de setups valida os dados reais, calendários e operadores, e divide
  o resultado pelos turnos antes da validação. Sufixos protegidos não deslocam.
- `PROTECTED_CONTEXT_VERSION` passa a 2; candidatos anteriores ficam obsoletos.
  Não mudou a versão de snapshots, a hierarquia de objetivos nem qualquer
  regra específica de referência. Sem alterações visuais ou novos cartões.

Dez regressões novas cobrem as três origens de proteção, identidade alternativa,
imutabilidade, idempotência, fonte protegida, campanha interrompida e redivisão
no limite de turno. No código anterior, os casos comportamentais reproduzem
a alteração de fragmentos, descarte de antecipação e reversão por `outside_shift`.
Os restantes testes cobrem o contrato explícito agora propagado entre helpers.

Backend final: **2186 passaram, 2 ignorados**, 438,87 s. Frontend: **188 passaram**
(22 node, 166 Vitest); lint, TypeScript/build e Ruff passaram. Os dois testes
ignorados são os opt-in preexistentes de responsividade/base real. Mantém-se
o aviso preexistente de bundle superior a 500 kB.

Frontend privado, 390/1440 px: remover uma indisponibilidade na M2, pré-visualizar,
aprovar e aplicar antecipou o lote livre D2 -> D0, mantendo exatamente os dois
fragmentos fixos da M1. Dois lotes de 100 peças, dois setups e 60 minutos de
preparação conservados. Candidato durável e plano aplicado iguais; nove campos
da API iguais após reinício. Prints do Gantt e tabela e navegação em leitura.
O ensaio é uma fixture futura genérica, não uma alteração da produção de setembro.

### Dados Reais E Limites

Dez normalizações retrospetivas da cópia da revisão 89 repetiram a mesma
assinatura, com física, quantidades, entregas e setup sem agravamento:
BFP082 inicial D4 09:49 -> D0 09:15; VUL195/VUL174 D11 -> D8 07:30/11:11;
BFP080 de D11 12:27 -> D11 08:45. BFP112 inicial já está no D4 12:20 neste
snapshot; isto não prova como estava na imagem antiga. Permanecem 195 setups
e 9075 minutos. A análise remove provas de execução apenas de cópias; conserva
as decisões manuais. Não demonstra ótimo nem ausência de outras melhorias.

Medição sequencial, dez ensaios por versão sem a suíte a correr: p50/p95
4,973/5,108 s antes, 5,175/5,486 s depois. As posições dos lotes nomeados são
iguais nas duas versões; a diferença mede o custo adicional da validação e
proteção, não uma melhoria de desempenho global. Não é média de produção.

Uma comparação privada para manter `LOT_TWIN_BFP079_22` na PRM031, D14 08:00,
terminou inconclusiva em 50,12 s, preservando a origem. Não é prova de que
essa transferência seja necessária, nem de impossibilidade da alternativa.
A imagem de 24/09 não corresponde à atual posição desse lote no D14.

Com as proteções históricas mantidas, a cópia do plano ativo continua válida
e os lotes analisados permanecem nas posições guardadas. O novo backend
arrancou numa cópia recente das bases, preservando os oito campos do frontend.
Código corrigido não reescreve o passado: falta esclarecer se setembro é
simulação reconstruível ou produção ocorrida antes de qualquer reconstrução
histórica. Auditoria integral, matriz histórica e prova das transferências
continuam abertas. Nenhum plano de produção foi aplicado para testar este bloco.

Artefactos: `/tmp/incompolinho-closure-full-final.xml`, `-before-final.xml`,
`-browser.json`, `-proof-{gantt,table}-*.png`, `-private-navigation.json`,
`-transfer-check.json`, `-release-baseline.json` e medições `-real-*.json`.
Estado: validado isoladamente; publicação será registada após guardas finais.
### Publicação Deste Bloco

Publicado no mesmo link, após backup consistente
`INCOMPOLINHO-backups/20261002T065737Z-protected-normalization`.
Oito ficheiros integrados com guarda da árvore; nenhum dado de produção
substituído. Na árvore publicada, 271 regressões backend e 188 testes frontend
passaram. Seis páginas públicas a 390/1440 px passaram em leitura, sem erros
JS/HTTP ou escritas. Guarda confirmou revisão 89, dataset, configuração,
558 segmentos, 202 lotes, indicadores, regras, ponteiro e payload intactos.

Artefactos públicos: `/tmp/incompolinho-closure-public-focused.xml`,
`-public-navigation.json` e prints associados. Serviços privados encerrados;
serviços públicos ativos nas mesmas portas e túnel. Este bloco está publicado;
os limites históricos e as restantes pendências acima não ficam concluídos.

## 27. Alternativas Construídas Perdidas Antes Da Validação

### Causa Reproduzida

`transfer_consolidation._rebuild` produz até quatro estados finais na comparação
geral e até 32 na comparação local. Os dois percursos cortavam a emissão em
`_VARIANTS_PER_HOP = 2`, antes de `improvement.consider` verificar física,
conservação, decisões protegidas e entregas por encomenda. Se as duas primeiras
alternativas fossem inválidas ou repetidas, uma terceira válida, já construída,
não chegava ao avaliador. O gerador esgotava-se como se tivesse verificado o
seu âmbito. A reprodução usa a mesma proposta válida do motor, duas variantes
fisicamente inválidas antes dela e identificadores alternativos.

Separadamente, `_rebuild` truncava estados intermédios com `[:beam_width]`
sem comunicar esse limite. Uma busca que não encontrasse melhoria nos ramos
conservados podia ser apresentada como concluída, mesmo tendo descartado
outras combinações. Não era timeout nem prova de impossibilidade.

### Correção Limitada Ao Percurso Comum

- Emitir todos os estados já construídos, conservando a ordenação e deixando
  o avaliador comum decidir. Não aumentar o beam, o horizonte, o grupo de seis,
  o número máximo de transferências ou o orçamento de 60 segundos.
- Os limites exteriores de propostas/deadline continuam ativos. Se o
  coordenador não conseguir avaliar tudo, a comparação continua parcial.
- Comunicar cada truncagem do beam como `scope_limited`, incluindo quando
  os ramos restantes morrem ou não reduzem setups. A cache de exclusões
  conserva esse estado, sem transformar repetição numa prova completa.
- Não alterar preferências industriais, setups físicos, OEE, aprovações,
  proteções nem regras específicas de referências. Sem novo elemento visual.

Sete regressões cobrem a terceira alternativa, aliases, comparação local,
truncagem efetiva de duas escolhas para uma, âmbito parcial no coordenador e
cache, e ausência de um falso limite numa pesquisa pequena não truncada.
As três primeiras falham comportamentalmente no código anterior; as restantes
verificam a nova propagação explícita do limite. 88 regressões focadas passaram.

### O Que O Ensaio Real Demonstra

Numa cópia só de leitura da revisão 89, sem provas históricas mas conservando
a decisão manual, a comparação padrão construiu propostas em cerca de 3,5 s.
Algumas deslocavam o predecessor de uma campanha com setup retido, deixando
a campanha seguinte sem montagem: a validação física rejeita-as corretamente.
Isto continua a exigir auditoria do fecho das dependências; esta correção não
inventa uma montagem nem força esses resultados a passar.

A comparação BFP079 para PRM031 que começa pelo lote `_22` ficou fora dos
24 blocos prioritários. Uma exploração diagnóstica alargada, apenas privada,
chegou a ela: a variante local não reduziu preparação e o bloco completo
continha dez campanhas, acima do limite de seis. Não houve prova de que
manter na PRM031 seja impossível ou de que a troca antiga seja necessária.
Nenhum destes ensaios alterou configuração ou plano ativo. A causa demonstrada
na terceira alternativa é global, mas não prova que seja a causa de todas as
capturas históricas. A análise das dependências e casos reais permanece aberta.

Artefactos: `/tmp/incompolinho-transfer-forensics.json`,
`/tmp/incompolinho-transfer-forensics-expanded.json`,
`/tmp/incompolinho-transfer-full.xml` e
`/tmp/incompolinho-transfer-search-browser.json`.
Regressão integral: 2194 backend passaram e um opt-in foi ignorado, 427,39 s;
188 frontend passaram. Lint, TypeScript/build e Ruff passaram. Mantêm-se o
aviso preexistente do bundle acima de 500 kB e avisos de limpeza de diretórios
temporários antigos do pytest. O ensaio da base real executou nesta cópia,
ao contrário do bloco anterior, que não tinha essa base privada disponível.

Frontend isolado a 390/1440 px: pré-visualização e aplicação exata, lote protegido
inalterado, recarregamento, reinício e seis páginas sem erro JS/HTTP. Oito campos
do plano ativo ficaram iguais ao arrancar o novo backend numa cópia recente
de produção. A fixture de aplicação testa segurança do percurso e não contém
uma transferência; a reprodução da terceira alternativa é uma regressão do
gerador/avaliador, não uma falsa demonstração desse caso no navegador.
Estado: validado isoladamente; publicação pendente das guardas finais.

### Publicação Verificada

Publicado em 02/10/2026 após backup consistente
`/home/luis/projects/INCOMPOLINHO-backups/20261002T083734Z-mounted-allocation`.
Na árvore pública, 255 regressões backend e 188 testes frontend passaram.
Seis páginas foram verificadas em leitura a 390/1440 px, sem erros JS/HTTP
nem pedidos de escrita. O mesmo túnel continua ativo.

As guardas de código, configuração, regras, bases e API confirmaram a revisão
89, o dataset `6d55d4d1d9094833aebdf62d89297d52` e os 558 segmentos intactos.
Não foi substituído o plano histórico. Os três serviços privados de ensaio
foram encerrados; a aplicação pública mantém os serviços existentes.
Captura da prova isolada: `/tmp/incompolinho-mounted-0700-detail.png`.

Este bloco está publicado. O fecho completo de dependências, a comparação
histórica BFP079 e a auditoria integral continuam abertos; a captura isolada
não demonstra uma alteração automática dos horários de setembro em produção.

## 29. Dependências De Montagem Omitidas Nas Transferências (02/10/2026)

### Causa E Reprodução

`transfer_consolidation._rebuild` libertava apenas a campanha movida e os
bloqueadores dentro da janela estimada. Um lote seguinte sem setup podia ficar
fixo apesar de depender fisicamente do predecessor removido. No outro sentido,
inserir uma campanha podia desfazer a montagem de um sucessor fora dessa janela.
O resultado era recusado por `missing_tool_change_setup` ou terminava tarde;
existia uma alternativa completa, mas a pesquisa não a construía.

A reprodução genérica tem T na M1 e depois na M2; U tem dois lotes na M1,
com o segundo sem setup. Manter T na M1 e alocar ambos os lotes U na M2
conserva as entregas e reduz setups 3 -> 2, sem mudar quantidades ou identidades.
Outra reprodução exige incluir também o predecessor de U, que está fora da
janela deslocada: mover apenas o sucessor não conserva a montagem necessária.
As duas variantes repetem-se com outros identificadores e saídas gémeas.

### Correção E Segurança

- Construir, uma vez por contexto, as dependências cuja montagem é provada
  pelo predicado físico partilhado `retained_setup_at`, com preparação nominal
  reconstruída dos lotes. Não usar apenas anotações antigas ou proximidade.
- Antes da alocação, fechar sucessores dos lotes removidos. Após inserir,
  incluir o componente de montagem dos lotes fixos que perderam a prova,
  incluindo predecessores necessários; repetir grupos sem duplicar estados.
- Nunca libertar lotes históricos ou manuais. A validação comum continua a
  recusar qualquer conflito físico, alteração protegida ou perda por encomenda.
- Conservar o limite de seis campanhas e o beam existente. Um fecho demasiado
  grande reporta `scope_limited`, com `setup_dependency_group_size`; não é
  prova de impossibilidade. Checkpoints conservam deadline e cancelamento.
- Um dependente conserva todas as suas máquinas compatíveis, incluindo uma
  terceira máquina diferente das duas da transferência. A hierarquia industrial
  e o contrato de setups não foram alterados; não há exceções por referência.
- `TRANSFER_SEARCH_VERSION = 2` integra a identidade de candidatos e cache.
  Snapshots mantêm `aps-v5`: o ensaio intermédio com uma versão geral nova
  recusou corretamente o arranque da cópia real; não foi publicado. A versão
  final invalida cálculos antigos sem exigir reconstrução do plano histórico.

15 testes novos neste módulo e um de identidade: nove reproduções comportamentais
falham no código anterior. Cobertura de aliases, testemunha completa, aplicação
do contrato, imutabilidade, idempotência, proteção, gémeas, terceira máquina,
limite honesto, cancelamento e reposição exata sem nova otimização.
146 regressões focadas passaram na versão final. Regressão integral final:
2237 passaram, 2 ignorados, 430,52 s; 188 testes frontend, Ruff, lint,
TypeScript e build passaram. Mantêm-se os avisos de limpeza de diretórios
antigos do pytest e bundle acima de 500 kB. A suíte intermédia de 2235 testes
antecede a separação final da identidade e não é contabilizada como fecho.

### Frontend E Dados Reais

No frontend isolado, a remoção de uma indisponibilidade fora da produção passou
por pré-visualização, aprovação e aplicação: T permaneceu na M1, D1 07:00-23:30,
U1/U2 passaram para a M2; 645 peças e entregas conservadas; setups 3 -> 2 e
90 -> 60 minutos, transferências 1 -> 0; cabeça ancorada intacta. O relatório
registou uma aceitação por `tool_transfers`. Aplicação igual ao candidato durável,
reload, reinício e navegação a 390/1440 px passaram com a identidade final.
Não é uma fotografia de uma alteração do plano de setembro em produção.

A cópia real da revisão 89 continua fisicamente válida. Na enumeração
retrospetiva, conservando a decisão manual, foram encontradas nove propostas
legais e sem perda por encomenda, contra cinco antes; há duas variantes
adicionais para BFP079 e duas para BFP184. Estes resultados da revisão 89
não são a comparação de 24/09: a imagem antiga tem 577 segmentos e o plano
ativo tem 558. Os grupos grandes e o limite de 24 hipóteses continuam explícitos.

Dez repetições sequenciais por versão, sem suíte concorrente: p50/p95
3,579/3,639 s antes e 5,116/5,446 s depois (mediana e nearest-rank p95).
São 29 -> 44 propostas e 5 -> 9 legais sem perda, com assinaturas estáveis.
A pesquisa mais ampla é mais lenta; não se apresenta como melhoria de
velocidade nem como média de produção. Ambas mantêm 12 limitações explícitas.

### Comparação Do Snapshot Histórico Exato

Encontrado na cópia de arquivo o snapshot `0801eea2ca2e472eb75c989f97a111e2`,
revisão 78, com 577 segmentos. BFP079 termina na PRM031 no D7 (24/09)
às 10:33; o lote `LOT_TWIN_BFP079_12` muda para PRM039, com 60 minutos
de setup. A comparação retrospetiva retira provas históricas apenas na cópia,
conserva decisões manuais e usa a configuração dessa versão, não a atual.

Foram construídas quatro alternativas completas, fisicamente válidas e sem
perda por encomenda, conservando IDs e quantidades. Mantêm o lote na PRM031
desde D7 10:33 sem setup e reatribuem campanhas compatíveis de BFP184,
BFP171, BFP162, BFP114 e BFP083 conforme a variante. Recalculam a duração
com OEE 0,44 da PRM031, contra 0,66 da PRM039; não reutilizam minutos da
máquina mais rápida. Setups 198 -> 197, minutos 9270 -> 9210. Uma variante
conserva 22 transferências globais; as outras têm 23 ou 24, por contrapartidas
permitidas pela hierarquia estável que prioriza setups sobre transferências.

A mesma comparação no código anterior a este bloco constrói as quatro
alternativas. Portanto, este ensaio prova que a troca antiga não era uma
necessidade física demonstrada, mas não atribui a este novo fecho a descoberta
desse caso. A aplicação abre o snapshot guardado e protege produção passada;
publicar código não recalcula nem substitui automaticamente esse histórico.
A variante não foi aplicada à produção. O beam continua limitado: não é
prova de ótimo global. Evidências completas nos ficheiros
`/tmp/incompolinho-transfer-dependencies-archive{,-before}.json`.

Artefactos: `/tmp/incompolinho-transfer-dependencies-before.xml`,
`-focused-final.xml`, `-full-final.xml`, `-real-after.json`, `-browser-final.json`,
`-private-navigation-final.json`, `-benchmark-{before,final}.json`,
`-proof-detail.png` e prints associados.
Estado deste bloco: publicado e verificado, conforme fecho abaixo.

### Fecho E Publicação Das Dependências

Publicado no mesmo link após backup consistente
`INCOMPOLINHO-backups/20261002T102401Z-transfer-dependencies`.
Seis ficheiros integrados com guarda de toda a árvore, sem sobrescrever
alterações concorrentes. Na árvore pública, 234 regressões backend e
188 frontend passaram; Ruff passou. Seis páginas públicas a 390/1440 px
passaram em leitura, sem erros JS/HTTP nem escritas. Guardas confirmaram
código integrado e estado durável/API intactos na revisão 89, com 558 segmentos.
Configuração, regras, indicadores, decisões manuais e histórico não mudaram.

A variante histórica escolhida pela hierarquia comum foi aberta num backend
privado com snapshot próprio. No frontend real, D7 24/09, BFP079 na PRM031
começa às 10:33, sem novo setup. Comparação com 197 setups/9210 minutos e
22 transferências globais, 3948232 peças conservadas; nenhuma perda por
encomenda. Os metadados de explicação foram recalculados antes da captura,
em vez de reutilizar anotações do arquivo. Leitura a 390/1440 px passou.
Artefactos: `/tmp/incompolinho-transfer-dependencies-archive-browser.json`,
`-archive-gantt.png`, `-archive-detail.png`, `-public-focused.xml` e
`-public-navigation.json`. Esta captura é uma reconstrução retrospetiva
isolada, não a substituição do plano público.

Os cinco serviços privados desta execução foram encerrados; os serviços
públicos e túnel existentes continuam ativos. Este bloco está publicado,
mas não conclui a matriz histórica nem a auditoria integral. Produção passada
permanece protegida; limites de pesquisa continuam explícitos.


Dez repetições sequenciais por versão, sem a suíte a correr: enumeração e
validação retrospetiva de transferências p50/p95 3,407/3,685 s antes e
3,625/3,837 s depois. As assinaturas repetiram-se em cada versão; o motor
novo emitiu 29 propostas em vez de 25. As cinco alternativas fisicamente
válidas, conservadoras de quantidade e sem perda de entregas mantiveram-se:
os quatro resultados adicionais deste snapshot não provaram melhoria nova.
O custo adicional é validação de hipóteses já construídas, não ganho de
velocidade. Não são tempos médios de produção nem um replaneamento integral.
Artefactos: `/tmp/incompolinho-transfer-search-benchmark-{before,after}.json`.

### Publicação Deste Bloco

Publicado no mesmo link com backup consistente
`INCOMPOLINHO-backups/20261002T073706Z-transfer-search-completeness`.
Quatro ficheiros integrados com guarda da árvore; 88 regressões backend após
integração passaram. Seis páginas públicas a 390/1440 px passaram em leitura,
sem erros JS/HTTP nem escritas. Guardas confirmaram revisão 89, dataset,
configuração, indicadores, decisões manuais, regras, ponteiro e payload
inalterados. Plano ativo não foi substituído. Este bloco não conclui a
justificação das transferências nem a reconstrução dos casos históricos.
Artefactos: `/tmp/incompolinho-transfer-search-public-focused.xml`,
`-public-navigation.json` e prints associados.

## 28. Tempo De Setup Reservado Antes Da Prova De Montagem (02/10/2026)

### Duas Causas Reproduzidas

Em `global_jit.py`, `_schedule_preemptive_run` passava sempre a preparação
nominal a `_find_preemptive_setup_slot`. A limpeza posterior podia remover
essa preparação, mas a produção e os lotes deslocados já tinham sido
alocados com o tempo extra. Uma proposta que piorasse uma entrega era
rejeitada antes de uma eventual compactação conseguir recuperar esse tempo.
Não era apenas a faixa visual: uma hipótese fisicamente executável não
chegava ao avaliador com os horários corretos.

Testemunha completa, com identificadores genéricos e repetida com aliases:
T termina montada em M1 no D0; no D1, outro lote T faz 30 minutos de produção
em M2 e U ocupa M1. T pode permanecer em M1, produzir 07:00-07:30 sem
preparação e deixar U nos seus horários originais, concluindo as duas
encomendas no D1. O alocador anterior acrescentava 30 minutos de setup a T
e empurrava o fim de U para D2. A testemunha legal, conservação e contrato
por encomenda passam; três testes comportamentais falhavam no código antigo.

O primeiro teste do frontend ainda falhou depois dessa correção isolada.
`improve_preserving_protected_lots` retirava o lote T do D0 para proteger a
sua posição. A compactação via a sequência completa, mas os geradores de
transferência e alternativa de máquina recebiam apenas o problema residual.
Sem o predecessor protegido, não enumeravam a transferência evitável nem
conseguiam provar a montagem retida. Duas novas regressões reproduziram a
perda de contexto; esta era uma segunda causa, não uma falha de apresentação.

### Correção Aplicada Na Cópia Isolada

- Consultar `retained_setup_at` antes de reservar preparação, com identidade
  comum de referência, família ou gémeas, excluindo a própria campanha.
  Havendo prova, reservar diretamente o início produtivo disponível; caso
  contrário, conservar a preparação nominal e a capacidade da equipa.
- Manter a preparação nominal no lote/campanha para futuras reinstalações.
  Retenção não elimina OEE, materiais, calendário ou necessidade de operadores.
- Transferências e alternativas recebem o plano físico completo, com provas
  explícitas para todos os lotes protegidos. Usar os dados completos, sem
  somar novamente as reservas residuais de operadores ou de preparação.
- Antes de devolver uma proposta residual, recusar alterações nos horários
  físicos ou conteúdo dos lotes protegidos. Validar e comparar o resultado
  completo pelo contrato existente; nunca eliminar uma alteração protegida
  silenciosamente para aproveitar o tempo que ela teria libertado.
- Incrementar o contexto protegido para 3, invalidando candidatos calculados
  com o percurso anterior. Não migrar nem recalcular snapshots históricos.

28 regressões permanentes cobrem as duas causas, aliases, imutabilidade,
idempotência, máquina fria, afinação diferente, ferramenta transferida,
preparação incompleta, família, gémeas, operadores, máquina, ferramenta,
equipa de setup, cancelamento, seis comparações com um oráculo finito e
tentativas de alterar posição/quantidade protegidas nos dois geradores.

### Prova No Frontend E Limites

Na fixture privada de novembro, com o lote do D0 ancorado, remover uma
indisponibilidade fora da produção analisada passou pelo ecrã de configuração,
pré-visualização, aprovação existente e aplicação. A segunda versão passou:
T permanece em M1 e começa às 07:00 no D1 sem preparação adicional; U
conclui no D1; 1010 peças conservadas; OTD e OTD-D 100%; setups 3 -> 2,
90 -> 60 minutos; transferências 1 -> 0; lote protegido intacto.
Os segmentos/lotes aplicados são exatamente o candidato durável apresentado.
Nove campos permaneceram iguais após reiniciar e seis páginas passaram
em leitura a 390/1440 px, sem erro JS/HTTP ou escrita inesperada.

Artefactos: `/tmp/incompolinho-mounted-browser.json` (primeiro ensaio falhado),
`/tmp/incompolinho-mounted-browser-v2.json` (percurso corrigido),
`/tmp/incompolinho-mounted-private-navigation.json` e
`/tmp/incompolinho-mounted-0700-gantt.png`.

A cópia real da revisão 89 passou validação física e de quantidades sem
alteração. A enumeração retrospetiva, sem provas históricas mas conservando
a decisão manual, voltou a encontrar cinco propostas legais sem perda por
encomenda, antes e depois. Esses ensaios não demonstram que a transferência
histórica BFP079 seja necessária ou que todas as suas dependências estejam
resolvidas. A correção é estrutural e a testemunha completa está demonstrada;
não constitui prova de ótimo global nem autorização para reescrever o passado.

Regressão integral final: 2221 testes backend passaram, 2 ignorados, 478,21 s.
28 testes novos e os testes de identidade/contexto passam; 188 frontend,
Ruff, lint e TypeScript/build passaram. Mantêm-se os avisos preexistentes
de limpeza de diretórios antigos do pytest e bundle acima de 500 kB.
Uma execução integral intermédia foi interrompida para incluir as últimas
regressões e a versão 3; não é contabilizada como verificação concluída.

Dez repetições sequenciais por versão, sem a suíte a correr: enumeração e
validação de transferências p50/p95 3,613/3,848 s antes e 3,597/3,698 s depois.
Assinaturas estáveis em cada versão; 29 propostas, cinco legais e sem perda,
12 limitações de âmbito nas duas versões. Não prova ganho significativo
de velocidade, melhoria nova desse snapshot ou um replaneamento integral.
Artefactos: `/tmp/incompolinho-mounted-benchmark-{before,after}.json` e
`/tmp/incompolinho-mounted-final-full.xml`.

O frontend foi novamente verificado com a versão final do contexto em
`/tmp/incompolinho-mounted-browser-v3.json`; a captura do detalhe do segmento
confirma início 07:00, fim 07:30, em M1. A automação auxiliar de captura tentou
inicialmente encontrar ID/hora numa tabela que não apresenta essas colunas;
essa asserção do script foi corrigida usando o detalhe real do segmento.
Não foi alterada a tabela nem acrescentado elemento visual à aplicação.
Estado: validado isoladamente; publicação pendente das guardas finais.

## 30. Leituras Antigas E Carga Sem Capacidade (02/10/2026)

### Causas Reproduzidas

`CapacityView` recarregava apenas ao mudar entre dia e semana. `JournalPage`,
`RulesPage` e `LateDeliveriesModal` consultavam uma única vez na montagem.
Uma revisão ou um ISOP novo podiam manter dados do plano anterior, incluindo
erros já ultrapassados. Três destes leitores não tinham proteção própria
contra respostas posteriores à desmontagem. O leitor do
journal não enviava a identidade esperada, apesar de o backend já suportar
essa verificação.

Em `analytics/capacity.py`, três divisões devolviam 0% com capacidade zero,
mesmo existindo produção. Máquinas inativas eram omitidas incondicionalmente,
incluindo as que ainda tinham carga. O diagnóstico escondia a inconsistência;
não era uma autorização física do motor. A interface também não suportava
utilização indefinida e podia chamar `toFixed` sobre `null`.

Antes da correção, 20 testes frontend falharam (19 leitores/apresentação e um
contrato HTTP); oito dos dez novos testes backend falharam. Os dois controlos
de recurso fechado sem carga já passavam. Artefactos `-frontend-before.xml`
e `-backend-before.xml`, prefixo `/tmp/incompolinho-analytic-consistency`.

### Correção E Contrato

- Os quatro leitores usam `usePlanQuery`, a proteção existente por dataset,
  revisão e parâmetros. Invalidam valores/erros antigos, conservam o filtro
  dia/semana e ignoram respostas de gerações anteriores. Sem novo mecanismo
  de polling nem alterações nas permissões.
- `getJournal` usa `analyticGet`, com os mesmos headers e conflito 409 das
  outras consultas. Não altera a revisão local com uma resposta analítica.
- Utilização é `null` quando existe carga sem capacidade; zero continua a
  significar ausência de carga. Máquinas inativas com trabalho permanecem
  visíveis com capacidade zero; as inativas vazias continuam excluídas.
- Os tipos e células existentes apresentam "Sem capacidade" em vermelho,
  sem novos cartões. O texto pode quebrar linha nos períodos semanais.
  Não se muda a alocação, configuração, disponibilidade ou regra industrial.

### Provas E Limites

Regressões focadas: 27 backend e 30 frontend passaram. Suíte completa:
2247 backend passaram, dois ignorados, 424,02 s; 208 frontend passaram
(22 lógica e 186 UI). Ruff, lint e TypeScript/build passaram. Mantêm-se
avisos preexistentes de limpeza pytest, integração Starlette/httpx e bundle.

Uma fixture válida privada de novembro foi guardada/restaurada pelas rotas
reais. A aplicação permaneceu montada durante as alterações de revisão;
o botão existente "Atualizar dados" provocou novas leituras em Capacidade,
Regras e Diagnóstico. Atrasos foi montado num harness privado com o mesmo
componente, store e endpoints, pois não tem entrada de navegação no Shell.
Os quatro componentes passaram a 390/1440 px, em StrictMode, com respostas
antigas retidas e entregues depois das novas. Quantidades e segmentos da
fixture permaneceram iguais em cada reposição; revisões foram monotónicas.
Os ensaios adicionais de utilização indefinida interceptaram apenas a resposta
analítica: são provas do contrato visual, não aplicações de um plano inválido.
Não houve erros JS/HTTP. As primeiras tentativas do script tiveram erros
de preparação do harness/rota, corrigidos sem alterações na aplicação.

Artefactos: `/tmp/incompolinho-analytic-consistency-browser.json`, dez prints,
`-backend-final.xml` e `-private-navigation.json`. As seis páginas da cópia
recente da produção passaram também em leitura a 390/1440 px. O novo backend
devolveu os oito campos da vista de produção iguais à baseline da revisão 89.
Este bloco corrige leitores e diagnósticos; não prova ótimo global nem corrige
horários históricos por atualização visual.

### Publicação Verificada

Publicado no mesmo link após backup consistente
`INCOMPOLINHO-backups/20261002T110203Z-analytic-consistency`.
Doze ficheiros integrados com guarda da árvore. Após integração, 27 regressões
backend e os 208 frontend passaram; `git diff --check` passou. As seis páginas
públicas a 390/1440 px passaram sem erros JS/HTTP ou escritas. Guardas confirmaram
dataset, revisão 89, ponteiro ativo, payload, configuração, regras, segmentos,
lotes, indicadores, mutações e decisões manuais intactos.

Artefactos finais: `/tmp/incompolinho-analytic-consistency-public-focused.xml`
e `-public-navigation.json`, incluindo os doze prints públicos. Os serviços
públicos/túnel mantêm as mesmas portas e endereço. Este bloco está publicado;
as provas históricas e de fecho integral listadas no progresso continuam abertas.

## 31. Controlos De Reposição E Revisão Nula (02/10/2026)

### Causas Reproduzidas

A rota usava `bool(body.get("recalculate", False))`. Em Python, `"false"`
é verdadeiro: uma reposição podia iniciar uma otimização involuntária.
Não está demonstrado que o frontend atual tenha enviado esse valor; o seu
pedido normal omite `recalculate`. O coordenador validava revisão apenas
quando diferente de `None`; a rota exigia a chave mas aceitava
`expected_revision: null`. A proteção contra alterações desde a leitura
do cliente ficava contornada, embora a proteção durante o cálculo existisse.
A função interna aceitava controlos ambíguos e revisões truncadas via `int`.
São defeitos de validação/reposição, não explicação de todos os horários
históricos ou escolhas de máquina apresentados pelo utilizador.

Antes da correção, 66 das 79 regressões iniciais falharam; 13 controlos
já passavam. Artefacto `/tmp/incompolinho-restore-contracts-before.xml`.

### Correção E Contrato

- `plan_writer` valida `recalculate` e qualquer revisão explicitamente
  enviada, incluindo `null`, antes de capturar estado.
- A rota reutiliza `_require_expected_revision` e `_approval_args`:
  revisão ausente/inválida é 400; obsoleta 409. Aprovações e recálculo
  exigem booleanos reais; não se atualiza a revisão para repetir escritas.
- A função interna valida sete controlos antes de descodificar/calcular
  e aceita só revisões integralmente representáveis. `None` mantém-se
  permitido nas chamadas internas de arranque/recuperação, não na API.
- `True` explícito continua a permitir recálculo. Omissão ou `False` repõe
  o snapshot sem otimizador. Gates, aprovação, histórico, journal e recibos
  mantêm-se. Sem mudança de preferências, regras ou versão de modelo.

### Provas E Limites

83 regressões permanentes passaram: entradas inválidas sem escrita,
validação antes de cálculo, revisões, reposição exata e replay idempotente.
O controlo `True` usa resultado controlado do otimizador: prova o dispatch,
não qualidade de um novo planeamento. Suíte completa isolada: 2330 backend
passaram, dois ignorados, 428,27 s; 208 frontend passaram. Ruff, lint e
TypeScript/build passaram, com os avisos preexistentes.

Frontend real privado a 390/1440 px: guardar, confirmar, mostrar rejeição
de pedido malformado, repor e repetir pelo recibo passaram. Horários,
quantidades, configuração industrial, mutações e decisões conservaram-se;
só identidade/revisão mudou. A primeira asserção do script incluía revisão
na comparação da configuração física; corrigida sem alterar a aplicação.
Reinício preservou os oito campos da vista aceite na revisão privada 5.

Cópia recente da produção: seis páginas em leitura a 390/1440 px, oito
campos iguais à baseline, revisão 89 e 558 segmentos. Artefactos com prefixo
`/tmp/incompolinho-restore-contracts`: `-browser-v2.json`, `-restart.json`,
`-private-navigation.json` e `-full.xml`. Sem aplicações de teste em produção.
A matriz histórica, transferências e fecho integral continuam abertos.

### Publicação Verificada

Publicado no mesmo link após backup consistente
`INCOMPOLINHO-backups/20261002T113615Z-restore-contracts`.
Seis ficheiros integrados com guarda da árvore. Na árvore pública, 219
regressões backend e os 208 frontend passaram; `git diff --check` passou.
Seis páginas públicas a 390/1440 px passaram em leitura, sem erros JS/HTTP
ou escritas. Guardas confirmaram revisão 89, dataset, ponteiro ativo,
payload, configuração, regras e os oito campos da API intactos.
Artefactos `-public-focused.xml` e `-public-navigation.json` com o mesmo
prefixo. Serviços públicos mantêm as portas e túnel. Este bloco está
publicado; não conclui os casos históricos nem a auditoria integral.

## 32. Contexto Protegido Nas Reparações De Prioridade (02/10/2026)

### Causa Reproduzida

`default_generators` entregava apenas o problema residual a três reparações:
`priority_inversions`, `campaign_tail` e `shift_exchange`. As reservas desse
problema protegiam a capacidade ocupada, mas não mostravam os segmentos que
provam a montagem anterior nem as datas de produção protegida. Compactação,
transferências e alternativas já tinham acesso ao contexto físico completo.
Uma fronteira de replaneamento podia, portanto, ocultar uma rotação legal
que reutiliza a montagem, apesar de o modelo físico comum aceitar a solução.

A reprodução reduzida tem uma cabeça protegida em M1 até 08:00 e uma produção
urgente da mesma ferramenta colocada no D1. A solução testemunha produz essa
continuação no D0 às 08:00, sem setup adicional, e conserva a outra entrega.
O gerador de prioridade residual não a encontrava. O teste repete-se com
identificadores diferentes: não foi criada uma exceção para BFP082.

Nos 15 testes novos, 11 falharam no módulo público anterior e quatro já
passavam. Estes quatro incluem o pipeline completo, cuja compactação inicial
já compensava esta fixture. A correção elimina uma divergência real entre
geradores; não se atribui a ela, sem reprodução, todo o comportamento histórico
ou uma melhoria que o pipeline completo já conseguia obter.

### Correção

Os três geradores reutilizam `allocate_in_complete_context`, tal como as
transferências e alternativas. Recebem produção protegida, configuração,
calendários e provas da montagem no mesmo contexto. A projeção de regresso
ao residual verifica segmentos e conteúdo dos lotes protegidos; qualquer
alteração é recusada. Não se consome novamente a capacidade através de
reservas do prefixo. Trade-offs permanecem no relatório existente.

`PROTECTED_CONTEXT_VERSION = 4` invalida candidatos calculados com a versão
anterior. Não migra horários históricos nem altera preferências, dimensionamento,
quantidades, regras JIT, limites de operadores ou orçamento de pesquisa.

### Provas E Limites

15 regressões permanentes, 137 testes focados e Ruff passaram. Suíte completa:
2345 backend passaram, dois ignorados, 431,90 s; 208 frontend passaram;
lint e TypeScript/build passaram. Mantêm-se os avisos preexistentes.

Frontend privado real a 390/1440 px: retirar uma indisponibilidade, calcular,
aprovar e aplicar passou. A produção urgente ficou no D0 às 08:00-08:15,
sem novo setup, com a cabeça protegida intacta e as 60 peças conservadas.
OTD passou de 66,7% para 100%; setups de três/90 minutos para dois/60 minutos.
Aplicação exatamente igual ao candidato, reload e reinício passaram. É uma
fixture sintética reduzida, não a reconstrução do ISOP histórico de setembro.

Seis páginas da fixture reiniciada e de uma cópia recente da produção passaram
em leitura a 390/1440 px. O backend novo conserva os oito campos da API pública
na revisão 89, com 558 segmentos. Artefactos com prefixo
`/tmp/incompolinho-protected-priority`: `-before-all.xml`, `-focused-v2.xml`,
`-full-final.xml`, `-browser.json`, `-application.json`, `-restart.json`,
`-private-navigation.json` e `-restarted-navigation.json`.
O print `-0800-detail.png` mostra o início produtivo na instância isolada.

Dez ensaios por versão na cópia real, com seed e dia de corte fixos:
p50/p95 7,560/7,670 s antes e 7,989/8,346 s depois. Pico RSS próprio
126,26/126,52 MiB. A leitura inicial de `ru_maxrss` incluía o máximo herdado
do lançador; as medições finais usam `VmHWM` de `/proc/self/status`.
O ganho é consistência entre geradores, não velocidade: a pesquisa ficou
ligeiramente mais lenta, ainda dentro dos dez segundos mais dois de fecho.
Todos conservaram quantidades, entregas, setups, histórico e origem; todos
terminaram parciais por limite de pesquisa, com uma melhoria aceite e 13
candidatos. Não são medições do pipeline completo de 60 segundos nem uma
prova de ótimo global. Artefactos `-benchmark-{before,after}-final.json`.

### Publicação Verificada

Publicado no mesmo link após backup consistente
`INCOMPOLINHO-backups/20261002T121456Z-protected-priority`.
Quatro ficheiros integrados com guarda da árvore, sem alterações concorrentes.
Na árvore pública, 137 regressões backend e 208 frontend passaram; Ruff e
`git diff --check` passaram. As seis páginas públicas a 390/1440 px passaram
em leitura, sem erros JS/HTTP ou escritas inesperadas.

Guardas confirmaram dataset, revisão 89, ponteiro ativo, payload, configuração,
regras, segmentos, lotes, indicadores, mutações e decisões manuais intactos.
Artefactos `-public-focused.xml` e `-public-navigation.json`, com doze prints
públicos. Serviços públicos mantêm as portas e o túnel; os quatro serviços
privados desta execução foram encerrados. Este bloco está publicado e
verificado; matriz histórica, enumeração do fecho e auditoria integral
continuam abertas. Não foi substituído o plano histórico em produção.

## 33. Confirmação Do Recálculo E Ausências De Operadores (02/10/2026)

### Causa Confirmada

O botão antigo `Recalcular plano` enviava primeiro um pedido sem aprovação.
`_recompute_transactional` calculava o resultado e recusava a aplicação quando
o gate exigia confirmação. O rollback conservava o plano ativo, mas descartava
o candidato. A confirmação do frontend enviava outro pedido com a aprovação;
o backend voltava a calcular, sem uma identidade que ligasse os dois resultados.
As rotas antigas de configuração e de dados mestre tinham o mesmo risco.
Dois testes permanentes falharam no código anterior: ausência de identidade
na confirmação e aplicação de um cálculo aprovado sem pré-visualização.

O coordenador comum conserva agora a resposta completa e o estado preparado
num candidato limitado e temporário, vinculado à rota, parâmetros, dataset,
revisão, modelo, configuração e identidade dos ficheiros. A confirmação usa
esse candidato, autoriza os seus gates e confirma snapshot/recibo pelo journal
existente. Não volta a chamar o motor. O estado preparado inclui os indicadores
e IDs gerados; não é uma reconstrução parcial do resultado. Conflitos físicos
não passam a ser aprováveis. Pedidos de aprovação sem candidato recebem
`409 preview_required`; origem, parâmetros ou ficheiros alterados invalidam-no.
Recálculos sem exceções continuam a poder concluir no primeiro pedido.

O frontend conserva candidato e identificador da operação entre o pedido e a
confirmação, inclusive em sessionStorage. Não repete automaticamente uma
escrita nem altera a revisão para ultrapassar conflitos. Perda de resposta
mantém a identidade para recuperar o recibo. Rascunhos diferentes não reutilizam
a aprovação. Não foram acrescentados cartões, regras industriais ou preferências.

Durante esta verificação foi reproduzida outra falha na API antiga de operadores:
`request_id` era percorrido como se fosse uma quantidade de pessoas. Essa rota
ignora agora os metadados da operação e usa o validador inteiro partilhado,
sem truncar frações ou aceitar booleanos como contagens.

### Prova Executável Das Ausências

Fixture versionada `operator_absence_2026-09-21.json`, com relógio em 17/09,
quatro máquinas Grandes, equipas A/B de 6/5 pessoas, um operador por máquina
e ausência de três em cada equipa de 21/09 00:01 a 27/09 23:59.
O intervalo é medido por varrimento independente dos segmentos produtivos;
não se usa o indicador do motor para provar o próprio limite.

Percurso real no frontend isolado, com aplicação explícita e prints a 390/1440:

| Estado | Máximo simultâneo A/B | Ausências |
|---|---|---|
| Inicial | 4/4 | Nenhuma |
| Adicionar A e B | 3/2 | Ambas |
| Retirar apenas A | 4/2 | Apenas B |
| Retirar B | 4/4 | Nenhuma |
| Recalcular e confirmar | 4/4 | Nenhuma |
| Reiniciar backend | Plano exato conservado | Nenhuma |

6000 peças conservadas em todas as fases. Até aplicar, o plano ativo permanece
igual. A confirmação do recálculo chamou a compactação uma única vez; segmentos
e lotes aplicados são iguais ao resultado capturado, e a aprovação ficou no
snapshot durável com o ID desse candidato. Reload e reinício conservaram os
oito campos da vista aceite, na revisão privada 6.

Artefactos: `/tmp/incompolinho-operator-flow-browser-v6.json` e respetivos prints;
`scripts/operator_absence_fixture.py` lança apenas a instância privada em 18058,
com armazenamento próprio em `/tmp/incompolinho-operator-flow-*`; o endpoint
de prova só existe nesse lançador de teste, não na aplicação pública.
`scripts/audit_operator_absence_flow.mjs` aceita apenas o frontend privado 54254.
Os primeiros ensaios tiveram erros no harness: labels exatos, classificação
do 409 esperado e consulta da prova fora do proxy. Não foram bugs da app e
não são contados como provas anteriores de sucesso.

26 regressões novas de identidade/confirmação, dados mestre e validação de
operadores; duas regressões de capacidade com IDs reais e renomeados; quatro
regressões frontend de confirmação, perda de resposta, rascunho e revisão.
Os testes antigos de CRUD passam agora pelo cálculo e confirmação identificada,
em vez de enviar aprovação indiscriminada no primeiro pedido. A verificação
de falhas de disco e rollback mantém-se, não foi removida.

Esta prova cobre o ciclo das ausências e o recálculo de um resultado aprovado.
Não demonstra que todo o plano histórico tenha sido corrigido, nem fecha os
ensaios reais BFP079/BFP112/BFP082, a enumeração completa ou os benchmarks
do pipeline inteiro de 60 segundos. A revisão pública 89 foi validada numa
cópia sem alterar dataset, plano, indicadores, configuração ou decisões manuais.
Publicação deste bloco pendente da regressão integral e das guardas finais.

Regressão integral: 2373 backend passaram, dois ignorados; 212 frontend
(22 de lógica e 190 de UI), Ruff, lint e TypeScript/build passaram.
O aviso de bundle acima de 500 kB já existente mantém-se; não se aumentou
o limite para o esconder. Artefactos `incompolinho-approval-backend-full-v3.xml`
e `incompolinho-approval-focused-v6.xml`. Publicação aguarda as guardas finais.


### Publicação E Verificação Final

Publicado após backup consistente `20261002T133340Z-approval-identity`.
Integração limitada aos 16 ficheiros deste bloco, sem substituir o plano ativo.
Na árvore pública passaram 242 regressões backend, 212 frontend, Ruff, lint,
TypeScript/build e `git diff --check`. Guardas confirmaram snapshot ativo,
revisão 89, regras, configuração e oito campos da vista iguais ao baseline.
Backend e frontend reiniciados nas portas existentes, com o mesmo túnel.

Seis páginas públicas e privadas verificadas a 390/1440 px; produção testada
apenas em leitura, sem erros JS/HTTP ou escritas inesperadas.
Artefactos: `/tmp/incompolinho-approval-public-navigation.json` e
`/tmp/incompolinho-approval-private-navigation.json`, ambos `passed`, com prints.
O endpoint privado de prova devolve 404 em produção. As três instâncias
privadas foram encerradas após a validação. O print privado comprova a fixture
de capacidade; o público não é prova de correção retroativa dos lotes históricos,
que ficaram intactos. A auditoria integral permanece aberta nos limites acima.

## 34. Orçamento Do Recálculo E Reproduções Nomeadas

### Causa Demonstrada

O frontend envia `compact_active_plan: true` ao carregar em Recalcular plano.
`backend/api/data.py::_compact_active_schedule` limitava a melhoria através
de `compact_preserving_started_lots`, mas chamava depois
`_attach_robustness_score` sem scope exterior. O limite de dez segundos da
melhoria não abrangia robustez, gates ou indicadores finais. O benchmark da
melhoria isolada também não media este percurso completo.

A função passa a estabelecer um único scope de 60 segundos, nunca maior que
o deadline recebido. Reutiliza `_attach_robustness_with_reserve`, com dez
segundos de reserva para gates e indicadores. Expirar só a avaliação de
robustez limpa percentagens antigas e mantém a aprovação atual para avaliação
inconclusiva; não apresenta o resultado como robusto. Expirar o orçamento
exterior ou cancelar propaga a interrupção, e a transação conserva o plano
anterior. Não se alteraram objetivos, calendários, permissões ou limites.

`tests/test_api_compaction_budget.py` reproduz deadline ausente, percentagem
herdada após avaliação incompleta e reinício indevido do limite em scopes
aninhados: três falhas anteriores. Acrescenta cancelamento e interrupção durante
indicadores finais para verificar rollback. Os testes não dependem de esperar
um minuto: usam relógio controlado e o caminho real de compactação/transação.

### Provas Dos Casos Pedidos

Fixture versionada `tests/fixtures/planning_opportunities_2026-09-17.json`,
relógio fixo em 17/09. São reduções das classes de problemas, não os dados
privados completos ou uma reconstrução retrospetiva do ISOP.

| Caso | Condição verificada | Resultado |
|---|---|---|
| BFP112 | Equipa de setup ocupada e operador ausente até 12:20 no dia anterior | Produção antecipa D5 -> D4 12:20; setup 11:50 |
| BFP082 | Procura urgente D0 e produção menos urgente à frente | Produção urgente D0 07:30, completa no D0, sem intervalo artificial |
| BFP079 | Gémeas e referências elegíveis em PRM031/PRM039 equivalentes | Zero transferências; no máximo dois setups físicos |

24 regressões permanentes executam ciclo, compactação, API e otimização
completa com identificadores reais e renomeados. Verificam física, cobertura,
entregas sem perda, origem canónica, conservação de lotes/gémeas, snapshots e
imutabilidade da origem. Os casos confirmam correções dos blocos anteriores;
não se atribui a antecipação ou consolidação ao novo controlo de duração.

Os três percursos passaram no frontend real isolado a 390/1440 px:
Recalcular -> confirmação existente -> aplicação do candidato -> reload ->
reinício do backend. O motor executa uma vez, a revisão privada passa de 1
para 2, e segmentos brutos/lotes são exatamente iguais ao candidato e snapshot.
`plan-view` calcula três campos de diagnóstico numa cópia; essa diferença
documentada não é confundida com alteração de alocação.

Artefactos: `/tmp/incompolinho-named-ui-bfp112-v3.json`,
`/tmp/incompolinho-named-ui-bfp082-v2.json`,
`/tmp/incompolinho-named-ui-bfp079.json`, respetivos `-restart.json` e prints.
Os lançadores aceitam apenas armazenamento privado e frontend 54254. O endpoint
de prova não pertence ao backend público. Erros iniciais de preparação do
harness (normalização do YAML e diagnósticos da vista) foram corrigidos e
repetidos, não contados como falhas da app.

### Medição Do Percurso Completo

`scripts/benchmark_planning_pipeline.py` mede compactação, robustez e atualização
dos indicadores numa cópia da revisão 89, sem escritor de produção. Usa RSS
próprio via `/proc/self/status`, sem herdar o pico do processo lançador.

| Compactação real, dez execuções por versão | Antes | Depois |
|---|---|---|
| p50 / p95 | 16,164 / 17,327 s | 15,437 / 16,214 s |
| RSS máximo próprio | 144,67 MiB | 144,70 MiB |
| Robustez com deadline | 0/10 | 10/10 |
| Candidatos físicos, completos e sem perda | 10/10 | 10/10 |
| Fingerprints diferentes | 1 | 1 |

Os vinte candidatos coincidem, e a origem persistida permanece intacta.
Não se reivindica melhoria causal de velocidade com esta diferença de tempo.
Dez ensaios da cópia real com BFP079 bloqueada em 12-18/10 passaram:
p50/p95 58,201/58,252 s, RSS 160,17 MiB. As dez alocações coincidem;
nenhuma usa a ferramenta durante o bloqueio e não há peças em falta ou a mais.
Robustez concluída em cinco execuções; nas restantes cinco o orçamento termina
essa avaliação e o resultado fica não avaliado, sem percentagem herdada.
Todos requerem confirmação pelas regras atuais. O teste não demonstra que
a sequência é ótima ou que não existem antecipações adicionais em outubro.
Artefacto `/tmp/incompolinho-pipeline-bfp079-after.json`; o primeiro ensaio
exploratório sem artefacto não é usado para a medição. Regressão integral em curso.
O orçamento de outros percursos, a enumeração e a auditoria integral continuam
abertos; este bloco não autoriza reescrever setembro ou substituir o plano ativo.
Publicação pendente dos ensaios, regressão e guardas finais.

Regressão integral concluída: 2403 backend passaram, dois ignorados, em
467,13 s; 212 frontend (22 lógica, 190 UI), Ruff, lint e TypeScript/build
passaram. Avisos existentes de TestClient e bundle acima de 500 kB mantêm-se.
Artefacto `/tmp/incompolinho-named-budget-backend-full.xml`. A cópia recente
da revisão 89 arrancou com os mesmos oito campos da vista; seis páginas
privadas a 390/1440 px passaram só em leitura. Publicação aguarda backup e
guardas finais. Nenhum destes ensaios substituiu o plano ativo público.


### Publicação Deste Bloco

Publicado após backup consistente `20261002T144549Z-named-compaction-budget`,
com integração guardada de nove ficheiros. Na árvore pública passaram
146 regressões backend, 212 frontend, Ruff, lint, TypeScript/build e
`git diff --check`. Serviços reiniciados nas portas existentes; mesmo túnel
em `https://inside-arranged-county-wing.trycloudflare.com/`.

As seis páginas públicas a 390/1440 px passaram só em leitura, sem erros
JS/HTTP ou escritas inesperadas. Guardas confirmaram snapshot, revisão 89,
configuração, regras e oito campos da vista iguais ao baseline. Endpoint
privado de prova devolve 404 em produção. As instâncias privadas foram
encerradas. Artefactos de navegação `incompolinho-named-budget-public-navigation`
e `incompolinho-named-budget-private-navigation`, ambos `passed`.

Os prints das tabelas `incompolinho-named-ui-*-restart-table-1440.png`
comprovam apenas as reproduções reduzidas. O print público conserva o histórico
anterior e não prova antecipação retroativa. Este bloco conclui a correção
do orçamento deste percurso e as suas regressões; a auditoria integral,
a prova dos casos históricos completos e outros entrypoints continuam abertas.

## 35. Interrupções Nos Indicadores E Na Fronteira De Gravação

### Causa Raiz Reproduzida

O deadline do motor terminava antes de `update_schedule` em percursos distintos
da compactação corrigida na secção 34. `CopilotState._refresh_analytics` capturava
`Exception` nos sete indicadores, incluindo `PlanningTimeout` e
`PlanningCancelled`. O escritor podia assim apresentar sucesso e persistir
estado depois de uma interrupção. Também não verificava o limite após os
validadores de confirmação ou a preparação dos ficheiros.

Outro desvio estava na reserva: com doze segundos restantes, CPO e o percurso
protegido atribuíam sete à melhoria e dez à robustez, invadindo os dez reservados
para fechar. O movimento manual repetia a margem de cinco segundos. A
correção uniformiza os três percursos, sem mudar hierarquia ou preferências
industriais, nem acrescentar exceções por ferramenta.

### Alterações Estruturais

- `planning_scope` mantém verificação final por omissão. Só os escritores
  duráveis usam verificação explícita até à fronteira de commit; não transformam
  um recibo já confirmado em falha porque a resposta chegou tarde.
- `transactions.run_sync_mutation` e `plan_writer` estabelecem o limite exterior
  de cálculo, incluindo indicadores e confirmação. São mantidos os perfis
  longos do Copilot; tanto a chamada direta como o dispatcher transmitem o modo.
- `_commit` verifica antes/depois dos validadores, antes do journal e depois
  das substituições de ficheiros, antes da transação SQLite. Interrupção nessa
  fase executa a recuperação existente, conservando estado anterior e identidade.
- `_refresh_analytics` verifica antes/depois de cada cálculo e propaga
  `PlanningStopped`. Erros ordinários continuam isolados como anteriormente.
- Os executores antigos de configuração propagam também `PlanningStopped`,
  após repor o estado isolado. Deixam de converter uma interrupção de scope
  interno em JSON de erro genérico ou HTTP 400; conservam 504/409 da API.
- CPO, otimização com lotes protegidos e fecho de movimentos utilizam
  `closing_reserve` em vez de margens divergentes.

O limite é cooperativo: não se reivindica preempção de qualquer instrução
nativa, operação de filesystem ou commit SQLite. O ponto durável é indivisível;
uma confirmação tardia após esse ponto tem de devolver o resultado confirmado,
não uma indicação falsa de rollback. A captura/clonagem anterior ao cálculo e
o transporte HTTP não constituem uma prova de latência rígida por este patch.

### Testes E Provas

`tests/test_writer_budget.py`: 58 testes permanentes; 35 reproduções anteriores
confirmadas (24 nos indicadores/escritores, seis na reserva CPO/protegida,
uma no movimento manual e quatro nos executores antigos).
Os restantes são controlos e contratos suplementares,
não novas falhas alegadas. O harness inicial confundia o módulo `state` com a
instância exportada e esperava um journal abortado onde a recuperação o elimina;
essas falhas de ensaio foram corrigidas, não contadas como bugs da aplicação.

222 regressões focadas passaram; 212 frontend, Ruff, lint e TypeScript/build
passaram. Artefactos: `/tmp/incompolinho-writer-budget-before-v2.xml`,
`/tmp/incompolinho-writer-close-before.json`,
`/tmp/incompolinho-manual-close-before.xml` e
`/tmp/incompolinho-writer-budget-focused-v4.xml`.

Lançadores privados `writer_budget_fixture.py` e `audit_writer_budget_flow.mjs`:
percurso real Configuração -> OEE -> candidato -> Aplicar. Timeout num indicador,
cancelamento e timeout na preparação dos ficheiros mantêm revisão, configuração,
segmentos, payload durável e candidato pronto. Repetir o candidato e receber
uma confirmação tardia depois do commit aplica uma vez; repetição pelo recibo
e reload mantêm revisão 2. Prints a 390/1440 px e relatório
`/tmp/incompolinho-writer-ui-v1.json`, `passed`. Usa relógio controlado apenas
nos scopes privados; não altera `time.monotonic` global ou espera realmente
um minuto para simular a interrupção. Não é um benchmark de duração de solver.

Cópia SQLite recente da revisão 89 validada antes da integração, sem mudar os
oito campos da vista. Seis páginas a 390/1440 px passaram só em leitura,
artefacto `/tmp/incompolinho-writer-budget-private-navigation.json`. Plano
público não substituído. Publicação depende ainda da regressão integral,
backup e guardas; não conclui os casos históricos ou a auditoria integral.

Regressão integral: 2455 backend passaram, dois ignorados, em 482,86 s;
212 frontend, Ruff completo, lint e TypeScript/build passaram. Mantêm-se
os avisos de TestClient, bundle e limpeza de diretórios de testes anteriores.
Artefacto `/tmp/incompolinho-writer-budget-backend-full.xml`. O segundo ensaio
frontend também passou e conferiu segmentos/lotes duráveis contra o candidato
exato, artefacto `/tmp/incompolinho-writer-ui-v2.json`. O reinício e as medições
reais suplementares foram concluídos no registo abaixo; publicação pendente.

Verificação final suplementar: quatro reproduções dos executores antigos
falharam antes (`/tmp/incompolinho-master-interruption-before.xml`); 58 testes
novos passaram, incluindo dois contratos HTTP 504/409. O conjunto final de
211 regressões passou (`/tmp/incompolinho-writer-budget-focused-v5.xml`).
Está em repetição a regressão integral com essa última alteração.

Frontend final `/tmp/incompolinho-writer-ui-v3.json` e `-restart.json`, ambos
`passed`: aplicação exata, repetição do recibo, reload e reinício mantêm
snapshot/configuração/segmentos. Seis páginas da fixture passaram a 390/1440,
relatório `/tmp/incompolinho-writer-budget-fixture-navigation.json`.

Dez ensaios da cópia da revisão 89 com BFP079 bloqueada em 12-18/10:
p50/p95 50,815/50,849 s, RSS máximo próprio 159,36 MiB. Física, quantidades,
bloqueio de ferramenta e imutabilidade da origem passaram nos dez. Todos
parciais por orçamento e com robustez explicitamente não avaliada; sujeitos
às aprovações atuais. Nove alocações coincidem; uma execução termina numa alocação
diferente, também válida, com quatro em vez de seis melhorias aceites.
Não prova determinismo com corte por relógio ou ótimo. A medição cobre cálculo
protegido, não a aplicação HTTP/SQLite; não se reivindica aceleração causal
contra a secção 34 porque agora há menos tempo para avaliar robustez.
Artefacto `/tmp/incompolinho-pipeline-bfp079-writer-budget.json`.

Regressão integral final após a alteração dos executores: 2460 passaram,
dois ignorados e uma falha de repetibilidade com seed 123 (58 contra 54
setups), em 565,19 s. Artefacto
`/tmp/incompolinho-writer-budget-backend-final.xml`. Falha em investigação;
publicação pendente, sem eliminar o teste ou aumentar o orçamento.

Confirmação solicitada sobre produzir sempre o mais cedo possível:
o código publicado fixa a janela de material em cinco dias úteis e procura
antecipações admissíveis, mas não prova o primeiro início de cada lote.
`improvement_key` ordena entregas, setups e transferências antes do custo
temporal. A normalização e a pesquisa são limitadas; `partial` não prova
ausência de alternativas. A API pública continua na revisão 89 com
`improvement.status=not_evaluated` e sem relatório de melhoria. 71 testes
focados de JIT, preparação, contratos e comparação de candidatos passaram
na árvore pública, relatório
`/tmp/incompolinho-five-workday-confirmation-20261002.xml`; consulta sem
recalcular ou alterar o plano ativo. Não autoriza afirmar "sempre".

Correções suplementares deste bloco: o rasto do solver desaparecia quando
uma melhoria recalculava robustez, pois a captura de proveniência ocorria
depois de `_clear_robustness` apagar o gate. Captura agora anterior; o gate
físico é novo. O polimento nativo usava quatro trabalhadores e não recebia
a seed do pedido; agora usa um trabalhador e a seed explícita, inclusive
zero. Seis reproduções falharam antes
(`/tmp/incompolinho-solver-evidence-before.xml`); 83 regressões passaram
depois (`/tmp/incompolinho-solver-evidence-after.xml`). Não se atribui a
falha integral anterior apenas ao paralelismo: um corte temporal pode
interromper duas pesquisas em pontos diferentes.

Frontend final repetido a 390/1440: `/tmp/incompolinho-writer-ui-v4.json`
e `-restart.json` passaram. Cópia do plano público passou seis páginas em
leitura, `/tmp/incompolinho-writer-native-private-navigation.json`.
212 frontend, Ruff, lint e TypeScript/build passaram. Regressão integral
final `/tmp/incompolinho-writer-budget-backend-native-final.xml` em curso;
publicação pendente. Dez execuções nativas de uma sequência reduzida
produziram a mesma reorganização efetiva. Não é prova de ótimo ou de
repetibilidade universal em cálculos cortados pelo relógio.

Regressão final concluída: 2467 backend passaram, dois ignorados, em
540,12 s, incluindo o teste original de seed inalterado. A falha anterior
não é apagada nem esta passagem prova determinismo sob cortes por relógio.
Validação independente da cópia recente do plano ativo: 558 segmentos,
nenhuma violação física, de quantidade ou âncora. Ensaio real único PRM039
OEE 0,44, corte histórico D15: candidato válido em 50,887 s, RSS 157,08 MiB,
origem intacta, confirmação necessária; artefacto
`/tmp/incompolinho-pipeline-prm039-native-close.json`. Sem reivindicar média
ou p95 a partir de um único ensaio. Publicação em preparação.

Publicado o bloco 35 após backup consistente
`/home/luis/projects/INCOMPOLINHO-backups/20261002T162624Z-writer-deadline`.
Quinze ficheiros integrados; 171 regressões backend e 212 frontend passaram
na árvore pública, mais Ruff, lint, TypeScript/build e diff-check. Seis
páginas públicas a 390/1440 px passaram sem erros ou escritas, relatório
`/tmp/incompolinho-writer-budget-public-navigation.json`. Fonte conciliada
com a cópia isolada; runtime, configuração, regras, indicadores e plano
preservados na revisão 89. Mesmo link e portas. Endpoint de prova privado
404; servidores privados encerrados. Não substituiu o plano ativo, não
conclui a auditoria integral e não prova primeiro início de todos os lotes.
Foi solicitada a distinção entre simulação e execução efetiva de setembro;
as outras verificações permanecem ativas.

## 36. Melhoria Aceite Perdida Num Timeout Posterior

`optimizer._optimize` conservava apenas a construção inicial. A pesquisa
notificava candidatos melhores, mas um timeout numa construção ou normalização
posterior devolvia sempre `baseline`. O coordenador recebia esse resultado e
substituía a melhoria já retida. Uma compactação posterior podia voltar a
encontrá-la, ocultando a perda e repetindo trabalho; não é uma garantia.

Corrigido na cópia isolada: o otimizador retém uma cópia do último candidato
aceite, completo e validado contra os inputs canónicos. Observadores aninhados
conservam a reserva de robustez e notificam o coordenador; candidatos recusados
não são encaminhados. O polimento CP-SAT notifica também a sua aceitação antes
de normalizações posteriores. Timeout da pesquisa conserva o candidato;
cancelamento ou esgotamento do prazo exterior continuam a interromper o pedido.
O coordenador transporta a proveniência do solver ao reconstruir os gates.
Não se alterou a hierarquia de preferências, o orçamento ou as regras industriais.

A validação conferia `output_milestones`, mas não as datas duplicadas do lote.
Passa a verificar os campos agregados e aliases, usando a agregação já existente
do dimensionamento. Metadados descritivos antigos sem quantidade mantêm a
compatibilidade e as verificações físicas/quantitativas anteriores. A presença
de um lote antigo já não desativa a conferência de origem dos lotes atuais.

Provas permanentes: 40 testes em `test_candidate_retention.py`, incluindo os
três casos reduzidos BFP112/BFP082/BFP079, renomeação integral, percurso direto
e coordenado, polimento normal/deep/max, origem/duração/quantidades, aliases,
cancelamento, prazo exterior, gémeas e história preservada. Reproduções antes:
`incompolinho-last-candidate-before.xml`, `-provenance-before.xml` e
`-mixed-before.xml`. 211 regressões focadas passaram após a correção.

Primeira regressão integral: 2504 passaram, dois ignorados e duas falhas nos
testes de movimentos de gémeas com metadados descritivos antigos. Corrigida a
compatibilidade, sem alterar ou remover esses testes. Regressão integral final:
2507 passaram, dois ignorados, em 478,28 s; artefacto
`incompolinho-last-candidate-backend-final.xml`. As falhas anteriores ficam
registadas, não foram omitidas da avaliação.
Frontend: 212 testes, lint e TypeScript/build passaram. Percurso privado real de
OEE/aplicação/falhas/repetição/reload/reinício passou a 390/1440 px; artefactos
`incompolinho-last-candidate-writer-ui.json` e `-restart.json`.
Seis páginas da fixture passaram também nas duas larguras, sem erros ou
escritas (`incompolinho-last-candidate-fixture-navigation.json`).
Cópia recente da revisão 89: 558 segmentos sem violações físicas, quantitativas
ou de âncoras; seis páginas passaram em leitura nas duas larguras. Publicação
pendente. Nada disto prova primeiro início possível para todos os lotes nem
substitui os horários históricos do plano público.

Conferência adicional da janela de cinco dias: o snapshot público continua
com zero violações JIT e antecipação máxima de cinco dias úteis. Uma comparação
em cópia, com história anterior a D15 protegida, encontrou uma transferência
evitável de BFP181 e reduziu o custo temporal sem piorar entregas ou aumentar
setups: 14 para 13 transferências, em 16,998 s, RSS 142,40 MiB. O relatório
terminou `partial/search_limit`, não como prova de primeiro início possível;
artefacto `incompolinho-last-candidate-compact.json`. Não aplicado à produção.

Dez execuções na cópia real, BFP079 indisponível em 12-18/10, história
anterior a D15 protegida: todas completas, físicas, quantidades conservadas,
bloqueio respeitado e origem intacta. p50 50,852 s, p95 50,934 s, RSS máximo
160,50 MiB (`incompolinho-last-candidate-bfp079.json`). Nove alocações iguais
e uma diferente, também válida: não prova determinismo sob corte temporal.
Pesquisa parcial por orçamento e robustez explicitamente não avaliada,
sem amostras herdadas. Mede cálculo protegido, não o total de gravação HTTP.

Publicado o bloco 36 no mesmo link, com backup consistente
`/home/luis/projects/INCOMPOLINHO-backups/20261002T173127Z-last-candidate`.
Sete ficheiros integrados, sem alterações alheias sobrescritas. Após integração,
211 regressões backend, 212 frontend, Ruff, lint, TypeScript/build e diff-check
passaram; aviso de bundle existente de 533,40 kB mantido. Seis páginas públicas
a 390/1440 px passaram, sem erros, falhas de API ou escritas; artefacto
`incompolinho-last-candidate-public-navigation.json`. Guardas de código e
dos oito campos do plano passaram; runtime, snapshot, regras e configuração
intactos na revisão 89. Servidores privados encerrados; endpoint de prova 404.
Não substituiu nem recalculou o plano ativo; uma captura do gráfico público
mostra o snapshot existente, não prova uma reparação retroativa ou início
mais cedo possível para todos os lotes. Auditoria integral continua aberta.

## Bloco 37: prova física de montagem e recálculo autorizado (02/10)

A prova `retained_setup_at` somava preparações pelo ID de campanha. Uma troca
de molde ou de afinação entre dois fragmentos não apagava os minutos anteriores;
o erro inverso ocorria quando a mesma preparação física usava IDs diferentes.
`tool_is_mounted_at`, usado no diagnóstico, ainda ignorava preparação incompleta,
uso remoto do molde e atividade em curso. Reproduções: 16 falhas e três casos
verdes antes da alteração (`/tmp/incompolinho-mounting-before.xml`).

Correção comum: só a atividade depois da última quebra física de montagem
prova retenção. Mudança de molde/afinação na máquina e utilização do molde
noutra máquina reiniciam a prova. Produção anterior ou preparação nominal
completa provam a montagem; intervalos ociosos e mudanças de ID não a apagam.
Os diagnósticos reutilizam a mesma função, sem alterar regras ou preferências.

21 testes permanentes, incluindo movimentos manuais exatos. Regressão integral
2526 passaram, dois ignorados, 482,90 s; os dois testes manuais acrescentados
depois da recolha passaram juntamente com os 19 restantes. Frontend: 212
passaram, lint e TypeScript/build passaram; aviso anterior de bundle mantido.

Recálculo normal na cópia recente: 53,732 s, 89 para 90, mesma alocação de 558
segmentos, física, quantidades, âncoras e histórico verificados independentemente.
Recibo repetido sem duplicação. Seis páginas privadas passaram a 390/1440 px.
Não é prova de antecipação máxima: manteve a baseline válida como piso de entrega.

Auditoria da cópia aplicada: 202 lotes, 49 protegidos por histórico/decisão manual,
153 móveis em 152 campanhas; 236 combinações campanha/máquina verificadas em
2,080 s mantendo os restantes lotes fixos. Zero oportunidades de prefixo nas
mesmas máquinas, zero violações da janela JIT. Encontrados dois candidatos
completos mais cedo, com conservação, origem canónica, física e contrato por
encomenda verificados:

- BFP181, `LOT_BFP181_PRM019_3829548020_78`: 27/11 13:05 PRM019 para
  26/11 08:48 PRM043. Aceite também pelo ciclo existente de compactação.
- BFP186, `LOT_TWIN_BFP186_47`: 20/10 14:55 PRM043 para 20/10 08:30 PRM039.
  Sem perda de entregas nem aumento de setups. A etapa de alternativas está
  limitada a reparação de risco/inversões de entrega; não seleciona este
  desempate temporal de uma produção pontual. Não é explicado por falta de
  operadores ou por indisponibilidade. Limitação identificada, não corrigida
  por uma exceção à referência nem apresentada como impossibilidade.

Pesquisa ampla: BFP181 aceite, 14 para 13 transferências; estado
`partial/search_limit`, não ótimo global. Artefactos privados:
`/tmp/incompolinho-mounting-private-report.json`,
`/tmp/incompolinho-mounting-private-anticipation.json` e
`/tmp/incompolinho-mounting-private-navigation.json`.

Publicação e substituição do plano ativo ainda em preparação. Preservar
exatamente lotes anteriores ao dia corrente (D15, 02/10), incluindo continuações,
e a posição manual; não reconstruir setembro como se fosse produção não executada.

Entrega do bloco 37: cinco ficheiros publicados conjuntamente, backup
`/home/luis/projects/INCOMPOLINHO-backups/20261002T191127Z-mounting-evidence`.
256 regressões focadas passaram após integração. Aplicada a pré-visualização
`48d83d235d644e75ac2d04e3206dc0ce` do recálculo conservador existente,
sem nova otimização na aprovação: revisão 89 para 90, snapshot ativo
`046b5d08b9884672ba2f9cf7e0f024d7`. Mantém 202 lotes e 558 segmentos;
BFP181 antecipada conforme descrito, 14 para 13 transferências, setups 195
e 9075 minutos inalterados, OTD/OTD-D 96,5/99,1 inalterados. Recibo repetido,
validação independente, histórico, origem, quantidades, âncoras e reinício
passaram. Configuração e mutações mantidas; riscos existentes aprovados por
pedido expresso de substituição, sem contornar conflitos físicos.

Auditoria **posterior à aplicação pública**, artefacto
`/tmp/incompolinho-mounting-public-anticipation.json`: 236 combinações,
235 sem início anterior e um testemunho BFP186 completo, físico e sem perdas,
20/10 08:30 PRM039 em vez de 14:55 PRM043. Dois outputs de 21000 peças cada,
libertação D33, produção até D40, entrega D47. Não foi aplicada essa alternativa:
a etapa `alternative_repair` seleciona risco/inversões e exige melhoria de
entrega; não pesquisa todos os desempates temporais de lotes já dentro do
prazo. Não é falta de capacidade comprovada. Auditoria ampla dos seis âmbitos
existentes: nenhuma outra alteração aceite, `partial/search_limit`;
não prova inexistência de reorganizações mais amplas nem ótimo global.
Sem violações da janela JIT, máximo cinco dias úteis de antecipação.

Seis páginas públicas passaram a 390/1440 px, sem JS, falhas API ou escritas
(`incompolinho-mounting-public-navigation.json`). Captura focal BFP181 usa
o bloco real de 26/11: setup 08:18-08:48, produção começa às 08:48; a faixa
inclui preparação física necessária. Uma tentativa de captura sobreposta ao
reinício registou 502 transitórios no health; repetida após o arranque, sem
ocultar esses erros no teste. Não constitui prova de que todos os lotes foram
antecipados ao máximo. Servidores privados encerrados, mesmo link público.

### Bloco 38: cobertura das reinserções (03/10)

Continuação do caso BFP186: a árvore já continha pesquisa de antecipações
pontuais e reinserção de duas/três campanhas, mas o limite genérico de 12
propostas/64 hipóteses rejeitadas cortava enumerações finitas ainda com tempo.
Corrigida essa perda de cobertura, mantendo o deadline, avaliação física e
contrato por encomenda. Seleção reutiliza a proteção comum de histórico e
âncoras manuais. Sem exceções por referência nem alteração de objetivos.

38 regressões novas; 2584 backend passaram, dois ignorados; 212 frontend,
lint e TypeScript/build verdes. Dez compactações isoladas antecipam BFP186
para 20/10 08:30 PRM043, preservando 49 lotes protegidos e os compromissos;
p50/p95-nearest-rank 10,843/10,928 s para essa fase. Aplicação pela API,
repetição do recibo e navegador 390/1440 px verificados apenas na cópia.
Pesquisa ampla continua parcial; não demonstra ótimo global.

Detalhes/artefactos no bloco 38 de `plano-melhoria-automatica-progresso.md`.
Plano público continua revisão 90; esta entrega não reinicia o serviço nem
publica trabalho recente de outras tarefas existente na mesma árvore.
