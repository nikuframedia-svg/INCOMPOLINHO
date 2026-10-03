# Plano tecnico: melhoria automatica do planeamento

## Identificacao do documento

- Versao: 1.0.
- Data da especificacao: 29/09/2026.
- Projeto: INCOMPOLINHO / ProdPlan ONE.
- Estado: plano para implementacao; nao constitui um relatorio de correcoes executadas.
- Decisao funcional confirmada: automatizar melhorias sem piorar nenhuma entrega
  nem aumentar o numero ou a duracao total dos setups.
- Este documento substitui o plano anterior centrado em selecionar alternativas
  manualmente. A criacao deste documento nao altera codigo, configuracao ou dados
  de producao.

## 1. Objetivo e decisoes

O objetivo e automatizar a analise que o utilizador tem feito visualmente:
identificar producoes que poderiam comecar antes, prioridades aparentemente
invertidas, setups dispensaveis, transferencias de ferramentas sem beneficio e
capacidade recuperada que continua desaproveitada.

O sistema deve procurar essas oportunidades durante o calculo e incorporar as
melhorias admissiveis **antes de apresentar o candidato**. Nao deve depender de o
utilizador selecionar cada lote, encontrar um intervalo vazio e pedir uma
simulacao, nem de o programador alterar preferencias para cada ocorrencia.

### 1.1 Regra de automatizacao

Automatizar melhorias sem piorar nenhuma entrega nem aumentar o numero ou a
duracao total dos setups. Uma melhoria com contrapartidas pode ser apresentada
para decisao, mas nao incorporada silenciosamente.

As prioridades comerciais e regras industriais mantem-se. Nao sao criadas
excecoes por ferramenta, referencia, identificador de lote ou fotografia.

### 1.2 Limites da intervencao

- Nao substituir o solver.
- Nao alterar dimensionamento de lotes, inventar execucao ou separar referencias
  gemeas.
- Nao adicionar novos cartoes, um novo dashboard ou um redesign do Gantt.
- Nao alterar automaticamente o plano publicado: confirmacao, aprovacoes,
  controlo de revisao e persistencia continuam obrigatorios.
- Nao ocupar todas as maquinas a qualquer custo. Antecipar uma operacao pode
  consumir uma ferramenta ou operadores necessarios a outra mais urgente.
- Nao apresentar pesquisa limitada como prova de otimo global.

A nocao de antecipacao sem prejuizo aproxima-se dos planos ativos estudados em
[teoria de planeamento](https://homes.di.unimi.it/righini/Didattica/Logistica/MaterialeLog/S8e%20-%20Job%20shop.pdf).
Essa referencia conceptual nao constitui uma garantia de otimo global para este
modelo industrial, que inclui recursos partilhados, setups, JIT e outros limites.

## 2. Contexto dos casos

Os exemplos abaixo identificam os comportamentos que motivam a intervencao.
Fotografias e relatos orientam a reproducao, mas nao provam que todos os casos
tenham a mesma causa. Os resultados esperados dependem do snapshot, configuracao
e calendario concretos de cada teste.

### 2.1 BFP112 na PRM039: comecar no dia anterior

A pergunta e por que razao a producao comeca no dia seguinte quando existe
capacidade anterior. O teste deve considerar simultaneamente maquina, ferramenta,
operadores, material e equipa de setup.

No cenario anteriormente analisado, a distincao relevante era maquina livre as
10:50, equipa de setup disponivel as 11:50 e producao possivel as 12:20 apos
preparacao. Esses horarios pertencem aquele snapshot e nao devem ser codificados
como regra.

O criterio de sucesso e materializar a antecipacao admissivel, nao apenas indicar
que existe um espaco vazio. O inicio de setup e o inicio produtivo devem continuar
a ser distintos na validacao e na apresentacao.

### 2.2 BFP082: procura inicial e intervalo artificial

Existem dois problemas distintos:

1. Procura inicial urgente colocada depois de procura posterior.
2. Remocao visual de setup sem aproveitamento do intervalo libertado.

A solucao deve avaliar cobertura da procura inicial e corrigir a cronologia real.
Apagar uma faixa do Gantt ou deslocar o intervalo vazio para outro ponto nao
satisfaz o requisito.

O teste nao deve exigir uma entrega fisicamente impossivel no dia zero. Deve
demonstrar que uma oportunidade admissivel de melhorar a cobertura inicial nao
fica por utilizar sem motivo.

### 2.3 BFP079 entre PRM031 e PRM039

Elegibilidade nas duas maquinas nao demonstra equivalencia. OEE, duracao,
preparacao, disponibilidade e producoes deslocadas podem justificar uma
transferencia.

O sistema deve comparar candidatos completos, incluindo permanecer na maquina,
e nao justificar a decisao apenas pela velocidade nominal. A indisponibilidade
de 12 a 18 de outubro e as entregas de outubro anteriores as de novembro sao
regressoes obrigatorias.

Os testes devem incluir tanto casos em que permanecer e melhor como casos em que
a transferencia traz um beneficio admissivel. Nao se estabelece uma maquina
preferida para esta ferramenta no codigo.

### 2.4 Operadores e indisponibilidades

Grandes A/B com 6/5 operadores e tres ausentes por equipa devem respeitar
capacidades simultaneas de 3/2 quando cada maquina exige uma pessoa.

Ao remover a ausencia, o desconto deve desaparecer dos calendarios, dos
recalculos e da restauracao. Isso permite maior utilizacao quando houver trabalho
e recursos restantes disponiveis; nao obriga a ocupar quatro maquinas sem
necessidade.

O mesmo principio aplica-se a ferramentas e maquinas: libertar um recurso deve
invalidar os bloqueios antigos e voltar a avaliar as producoes afetadas.

### 2.5 Movimentos, horarios exatos e setups

Inicio produtivo as 07:00 pode exigir preparacao anterior. Manter a mesma
ferramenta pode dispensar instalacao, mas mudar de referencia pode exigir afinacao.
Timeout nao prova falta de capacidade.

Os exemplos da conversa passam a fixtures de regressao, acompanhados por variantes
com outros identificadores. O movimento puro conserva a mesma producao, incluindo
quantidades e outputs gemeos.

## 3. Diagnostico do codigo

### 3.1 Pesquisa parcialmente coordenada

`normalize_earliest_legal_plan` procura antecipacoes mantendo a atribuicao de
maquinas. `repair_alternative_machine_delivery` procura sobretudo melhorias
estritas de entrega. `repair_shift_capacity_exchange` cobre um padrao limitado e
usa limites de avaliacoes.

Cada rotina pode funcionar no seu dominio sem cobrir a combinacao que o
utilizador identifica. A correcao deve ampliar e coordenar a pesquisa existente,
nao substituir tudo por mais uma passagem independente.

### 3.2 Excecao incompativel com a regra sem perdas

A rotina de fim de campanha admite uma contrapartida limitada de atraso mantendo
indicadores agregados. O audit tambem exclui determinados intervalos associados
a essa politica.

Essa excecao deixa de autorizar aceitacao automatica. Familias de setup descrevem
compatibilidade fisica; nao concedem autorizacao implicita para piorar uma
entrega ou reservar o ultimo turno.

### 3.3 Criterios e execucao dispersos

Existem sequencias diferentes de normalizacao no scheduler, otimizador e
libertacao de capacidade. Algumas rotinas posteriores podem abrir oportunidades
depois de uma verificacao anterior.

O otimizador tambem usa texto de warnings para inferir se uma reparacao ja
ocorreu. Substituir esse controlo por informacao estruturada vinculada ao estado
efetivamente verificado.

### 3.4 Documentacao e restauracao

O documento de invariantes contem descricoes antigas incompativeis com o bloqueio
atual de falta de operadores. A restauracao tambem tem caminhos que recalculam
ou normalizam snapshots.

A entrega deve reconciliar a documentacao e impedir que uma atualizacao tecnica
substitua silenciosamente horarios guardados. Estes factos sao observacoes do
codigo; a associacao de cada um a um incidente concreto exige reproducao.

## 4. Contrato de aceitacao automatica

### 4.1 Validade obrigatoria

O candidato conserva procura, lotes, quantidades, outputs gemeos e marcos de
subcontratacao. Respeita maquinas elegiveis, OEE, calendarios, operadores, equipas
de setup, ferramentas, material e JIT.

Lotes protegidos e decisoes manuais fixadas permanecem intactos segundo a
validacao canonica. Nao se reduz nenhum limite fisico para permitir uma melhoria.

### 4.2 Referencia correta de comparacao

A fase de melhoria compara com um candidato completo valido para os inputs
atuais. Cada passo compara tambem com o ultimo candidato aceite.

Quando os inputs nao mudaram, incluir o plano ativo valido como referencia.
Quando mudaram, distinguir o impacto obrigatorio dessa alteracao, como menor OEE,
do impacto adicional das melhorias automaticas.

A garantia sem perdas aplica-se a fase de melhoria. Nao pode ser usada para
prometer que uma reducao de capacidade nao tera consequencias, nem para reutilizar
um plano antigo que deixou de respeitar os novos inputs.

### 4.3 Servico por encomenda

Reutilizar a alocacao cronologica existente, considerando stock, producao, gemeas
e fornecimentos comprometidos.

Para cada encomenda:

- A quantidade disponivel no prazo nao pode diminuir.
- O atraso nao pode aumentar.
- Verificar separadamente os marcos de expedicao para subcontratacao.
- Na ausencia de detalhe por cliente, usar os marcos canonicos de procura, sem
  omitir a protecao.
- Identificar de forma estavel entradas duplicadas, sem as fundir indevidamente.

Um OTD agregado melhor nao compensa uma encomenda individual pior. Esta verificacao
e adicional aos indicadores agregados usados para ordenar os candidatos.

### 4.4 Preparacao

Comparar numero de preparacoes fisicas e minutos totais; nenhum pode aumentar.
Fragmentos do mesmo setup nao contam como instalacoes independentes.

Usar a identidade fisica de preparacao e as familias configuradas, incluindo
reinstalacao apos utilizacao noutra maquina. Quantidades sao comparadas
exatamente; duracoes usam a precisao canonica existente, sem tolerancias que se
acumulem a cada iteracao.

### 4.5 Beneficio e desempate

Aceitar apenas uma melhoria estrita. Ordenar candidatos admissiveis pela
prioridade de entrega existente. Em equivalencia, usar a seguinte ordem:

1. Menos setups.
2. Menos minutos de setup.
3. Menos transferencias de ferramenta.
4. Menor custo temporal de producao.
5. Menos lotes alterados relativamente a referencia.
6. Menor deslocacao temporal relativamente a referencia.

A ordem fica fixa e testada, sem pesos ajustados por ocorrencia. A assinatura dos
estados visitados impede oscilacoes e repeticao de trabalho sem progresso.

### 4.6 Contrapartidas

Candidatos fisicamente validos que aumentem setups ou prejudiquem uma entrega
ficam fora da aceitacao automatica, mesmo quando melhoram o resultado agregado.

Guardar o impacto e apresentar uma sugestao no mecanismo existente. Uma sugestao
descritiva nao e autorizacao de aplicacao. Qualquer alteracao posterior exige
pre-visualizacao identificada e confirmacao pelo percurso existente.

## 5. Ciclo unico de melhoria

### 5.1 Capturar contexto

Trabalhar sobre copias coerentes de configuracao, dados, plano e identidades.
Determinar protecoes e ancoras uma vez.

Reconstruir calendarios quando mudam recursos e aplicar overlays temporarios uma
unica vez. Um movimento puro nao volta a executar dimensionamento de lotes.

### 5.2 Indexar recursos

Construir indices por maquina, ferramenta, grupo de operadores, equipa de setup
e intervalo. Gerar posicoes candidatas a partir de aberturas, fins de ocupacao,
libertacoes de material e alteracoes de capacidade.

Evitar testar todos os minutos ou recalcular o plano completo para cada posicao.

### 5.3 Gerar candidatos

Reutilizar antecipacoes de producao e continuacoes, compactacao apos remocao de
setup, reinsercao de campanhas, troca de sequencia e atribuicao a maquinas
alternativas.

Testar primeiro alteracoes locais; depois grupos relacionados pelos recursos em
conflito. Reutilizar o limite atual de seis campanhas para pesquisa coordenada.
Atingir esse limite significa ambito limitado, nao impossibilidade global.

Uma antecipacao pode reorganizar segmentos dentro do mesmo lote, mas nao criar
novos lotes, alterar quantidades ou separar referencias gemeas.

### 5.4 Avaliar centralmente

Os geradores propoem alteracoes, mas nao decidem publica-las. Um avaliador comum:

1. Materializa o plano completo.
2. Valida fisica e conservacao.
3. Calcula servico por encomenda e preparacoes.
4. Aplica o contrato sem perdas.
5. Compara o beneficio com o candidato corrente.

Tentativas rejeitadas nao podem modificar lotes, calendarios, score ou metadados
do candidato corrente.

### 5.5 Propagar consequencias

Apos aceitar uma alteracao, invalidar as avaliacoes dos recursos afetados,
incluindo outras maquinas que partilhem ferramenta, operadores ou equipa de
setup.

Reavaliar as sequencias seguintes ate o efeito deixar de se propagar. Quando a
dependencia nao puder ser delimitada com seguranca, repetir a pesquisa abrangente.
Uma alteracao de maquina invalida tambem o contexto que a classificacao anterior
usava.

### 5.6 Concluir coerentemente

Terminar por ausencia de melhorias admissiveis encontradas, orcamento, limite de
pesquisa ou ciclo detetado.

Fazer uma verificacao final sobre o candidato estabilizado. Se nao terminar,
indicar pesquisa parcial. So entao calcular as explicacoes e indicadores finais.

Nunca reutilizar explicacoes de um estado anterior nem afirmar que uma producao
nao pode comecar antes apenas porque uma heuristica falhou.

## 6. Organizacao da implementacao

### 6.1 Coordenador e tipos

Criar o modulo proposto
`/home/luis/projects/INCOMPOLINHO/backend/scheduler/improvement.py`, com
coordenacao, avaliacao e relatorio tipado.

Acrescentar o relatorio opcional ao resultado em
[types.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/types.py:225).
Os geradores devolvem propostas e recursos afetados. O coordenador mantem o
candidato aceite, assinatura fisica, avaliacoes reutilizaveis e motivos de rejeicao.

### 6.2 Scheduler e CPO

Consolidar as sequencias hoje presentes em
[scheduler.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/scheduler.py:3155)
e [optimizer.py](/home/luis/projects/INCOMPOLINHO/backend/cpo/optimizer.py:253).

Separar construcao, reparacao fisica obrigatoria e melhoria operacional. Preservar
os pontos de entrada publicos. Chamadas internas devem conseguir adiar a melhoria
ate existir o candidato completo, evitando executa-la repetidamente por cada
camada.

### 6.3 Operacoes e criterios

Adaptar os modulos seguintes ao avaliador comum:

- [gap_filling.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/gap_filling.py).
- [priority_normalization.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/priority_normalization.py).
- [alternative_repair.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/alternative_repair.py).
- [campaign_tail.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/campaign_tail.py).
- [shift_exchange.py](/home/luis/projects/INCOMPOLINHO/backend/scheduler/shift_exchange.py).

Retirar a aceitacao especial de atraso no fim de campanha e a exclusao automatica
dos respetivos intervalos. Preservar compatibilidade fisica das familias de setup.

Rotinas que encontram solucoes com setup adicional continuam uteis como geradores
de contrapartidas, nao como excecoes ao contrato.

### 6.4 Entregas e explicacoes

Acrescentar a comparacao por encomenda em
[order_tracking.py](/home/luis/projects/INCOMPOLINHO/backend/analytics/order_tracking.py:30),
com identidade estavel tambem para entradas duplicadas.

Reutilizar o mesmo contexto de recursos em auditoria e explicacoes. Separar
claramente bloqueio fisico, material/JIT, protecao manual/historica, contrapartida
e pesquisa incompleta.

### 6.5 Percursos e frontend

Integrar carregamento, recalculo, alteracoes de configuracao, libertacao de
capacidade, simulador e movimento manual. Nos percursos com historico, validar
sempre o resultado combinado.

Atualizar os tipos e as mensagens existentes no Gantt e relatorio de gates, sem
novo dashboard, novos cartoes ou edicao visual de horarios que nao corresponda ao
backend.

### 6.6 Restauracao e documentacao

Em [restore.py](/home/luis/projects/INCOMPOLINHO/backend/plans/restore.py:181),
separar validacao de restauracao de otimizacao. Arranque e leitura nao executam o
novo ciclo sobre o plano guardado.

Reposicao incompativel exige recalculo explicito ou diagnostico, nao correcao
oculta. Atualizar
[algorithm-planning-invariants.md](/home/luis/projects/INCOMPOLINHO/docs/algorithm-planning-invariants.md),
explicando a nova regra por encomenda e a remocao das excecoes de aceitacao
anteriores.

## 7. Contratos, identidade e persistencia

### 7.1 Relatorio aditivo

Introduzir `improvement_report` com:

- Versao do contrato.
- `status`: `completed`, `partial` ou `not_evaluated`.
- Motivo de paragem.
- Ambitos pesquisados.
- Contagens de candidatos e movimentos aceites.
- Duracao.
- Resumo de contrapartidas.

`completed` significa conclusao no ambito declarado, nunca prova de otimo global.
Snapshots anteriores sem relatorio sao apresentados como nao avaliados, nao como
concluidos.

### 7.2 API e apresentacao

Transportar o relatorio atraves do resultado e de `gate_report`, aproveitando os
contratos e snapshots existentes. Manter URLs e pedidos atuais.

A interface mostra as limitacoes nos locais ja usados para avisos e sugestoes.
Pesquisa parcial ou oportunidade com contrapartida nao deve, isoladamente, criar
um novo bloqueio fisico ou alterar as aprovacoes existentes.

### 7.3 Assinaturas e cache

Separar assinatura fisica usada para deduplicacao dos fingerprints completos
usados na aplicacao. A primeira deve incluir tempos, recursos, quantidades e
outputs, sem depender de warnings.

A cache inclui inputs, configuracao, protecoes, versao do modelo e ambito de
pesquisa. Existe apenas durante o calculo. Uma nova revisao ou alteracao de
calendario invalida resultados anteriores.

### 7.4 Aplicacao e reinicio

Melhorar o candidato antes de emitir a identidade aprovada. Aplicar continua a
consumir esse candidato, sem otimizacao adicional, com revisao esperada, recibo
idempotente e transacao existente.

Invalidar candidatos anteriores a publicacao. Nao usar uma atualizacao da versao
do motor como autorizacao para recalcular automaticamente o snapshot ativo.

## 8. Testes permanentes e aceitacao

### 8.1 Casos reais

Preparar fixtures versionadas para BFP112, BFP082, BFP079 e ausencias Grandes A/B,
com configuracao e relogio controlados.

Verificar a antecipacao efetivamente materializada, cobertura no prazo, setups
e restantes entregas. Para BFP079, testar OEE distinto e maquinas equivalentes;
nao impor que permanecer ou transferir seja sempre a resposta. Para ausencias,
cobrir retirar, aplicar, replanear e reiniciar.

### 8.2 Melhorias encadeadas e generalizacao

- Remover setup deve abrir capacidade utilizavel.
- Antecipar uma continuacao deve poder libertar recursos para outra maquina.
- Mudar uma campanha deve provocar nova avaliacao da origem e destino.
- Repetir com identificadores diferentes e permutacoes das listas.
- Nos casos concluidos, uma segunda execucao do ciclo deve ser idempotente.
- Em instancias pequenas, enumerar movimentos do ambito suportado e procurar
  testemunhos de melhoria omitida.

### 8.3 Contraexemplos de seguranca

Rejeitar automaticamente:

- OTD melhor que esconda piora individual.
- Setup adicional, mesmo com recuperacao de entrega.
- Producao durante ausencia ou uso duplo de ferramenta.
- Antecipacao antes de material.
- Alteracao de lotes protegidos ou ancoras manuais.

Manter a possibilidade de descrever contrapartidas validas. Cobrir gemeas, setup
repartido, fragmentos produtivos com quantidade zero, arredondamentos, procura sem
detalhe de cliente, subcontratacao e marcos anteriores a D0.

### 8.4 Integracao e falhas

- Igualdade entre candidato, aplicacao e restauracao.
- Troca de ISOP ou revisao durante calculo.
- Respostas fora de ordem.
- Cancelamento em construcao, melhoria e fecho.
- Timeout com e sem candidato completo.
- Falhas de gravacao e perda de resposta.
- Navegador a 390/1440 px, StrictMode e Consulta.
- Ausencia de novos cartoes e de discrepancias entre horarios desenhados e API.

### 8.5 Execucao e evidencias

Criar regressoes que falhem para as reproducoes confirmadas e preservar os testes
que ja protegem comportamento correto. Testes que esperavam a contrapartida
antiga devem passar a verificar proposta nao aplicada, nao ser simplesmente
eliminados.

Executar backend completo, `pnpm test`, `pnpm lint`, TypeScript, `pnpm build`,
analise Python e `git diff --check` nos ambientes do projeto.

Separar falhas preexistentes, resultados novos e benchmarks. Este documento nao
afirma que esses testes ja foram executados. O relatorio da implementacao deve
registar comandos, resultados e evidencias por caso.

## 9. Orcamento e desempenho

### 9.1 Deadline comum

Nos percursos normais de 60 segundos, reservar 10 para melhoria e 10 para fecho,
permitindo a melhoria aproveitar tempo nao usado pela construcao.

Se ainda nao existir candidato completo, a construcao pode usar o tempo de
melhoria ate ao limite de fecho. Nesse caso, declarar melhoria nao avaliada ou
parcial. Nao reiniciar o relogio em funcoes internas.

Perfis de calculo mais longos mantem os limites existentes e o mesmo contrato.
Reutilizar os mecanismos de deadline, reserva, cancelamento e cache de execucao
em [planning_control.py](/home/luis/projects/INCOMPOLINHO/backend/planning_control.py).

### 9.2 Trabalho limitado

Manter um candidato corrente, uma tentativa e resumos limitados de contrapartidas,
em vez de acumular copias de todos os planos.

Reutilizar scores e indices apenas quando a assinatura coincidir; invalidar
corretamente apos cada alteracao. Instrumentar avaliacoes, reconstrucoes,
validacoes, cache, motivos de rejeicao e tempo por fase. Nao determinar que algo
ja foi reparado atraves de texto de mensagens.

### 9.3 Medicoes

Executar dez repeticoes dos cenarios selecionados na mesma maquina, com inputs e
seeds controlados. Medir p50/p95, memoria e latencia da API durante calculo.

Exigir respeito pelo orcamento normal com tolerancia de fecho de dois segundos.
Comparar tambem tamanhos crescentes de planos e confirmar que nao regressa a
reconstrucao redundante de calendarios ou a pesquisa minuto a minuto.

Um timeout deve produzir um candidato ja validado ou erro explicito, nunca um
resultado parcialmente verificado. Robustez ou verificacoes nao concluidas nao
podem herdar resultados de outro candidato.

## 10. Sequencia de trabalho e publicacao

### 10.1 Preparacao e contrato

Criar copia isolada da arvore atual, incluindo alteracoes nao commitadas, e
fixtures consistentes dos dados. Registar baseline funcional e de desempenho.

Implementar primeiro comparacao por encomenda, assinatura fisica e testes do
contrato. Depois adaptar os geradores e retirar as excecoes incompativeis,
mantendo as validacoes fisicas existentes.

### 10.2 Coordenacao e integracao

Implementar o ciclo unico, invalidacao de dependencias e relatorio. Ligar todos
os percursos de criacao de candidatos e adaptar frontend e snapshots.

Executar regressoes por bloco, depois testes completos, cenarios reais e
navegador. Nao editar antecipadamente a arvore servida pelo Vite publico.
Reconciliar alteracoes entretanto feitas pelo utilizador antes da integracao.

### 10.3 Entrega

1. Validar uma copia recente do plano ativo sem o alterar.
2. Suspender a publicacao se surgir incompatibilidade nao resolvida.
3. Aguardar trabalhos ativos.
4. Fazer backup consistente de codigo, configuracao e bases SQLite.
5. Publicar backend/frontend juntos e manter portas e tunel.
6. Verificar producao apenas em leitura, incluindo identidade e horarios do plano.
7. Perante uma falha, executar rollback coordenado.
8. Entregar matriz caso, causa, alteracao, teste e resultado; medicoes antes/depois;
   e limitacoes de pesquisa remanescentes.

## Criterio final de conclusao

O utilizador deixa de ter de apontar repetidamente antecipacoes admissiveis ja
cobertas pelo motor. As melhorias sem perdas sao incorporadas no candidato.

Esperas restantes tem evidencia atual, uma contrapartida identificada ou uma
limitacao de pesquisa assumida. A conclusao nao depende de exemplos especificos
passarem por acaso, nem de declarar o sistema "100% correto".
