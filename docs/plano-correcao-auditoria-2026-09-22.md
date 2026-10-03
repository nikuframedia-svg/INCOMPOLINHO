# Auditoria e Plano de Correcao

Data: 22 de setembro de 2026. Projeto: INCOMPOLINHO.

## 1. Ambito e Resultado

**Este documento e apenas um plano. Nao foram alterados codigo da aplicacao, configuracao, plano ativo ou dados de producao; nao houve publicacao.** Os ensaios de escrita usaram bases temporarias. No navegador, os pedidos de alteracao foram intercetados, sem chegar ao servidor.

A auditoria abrangeu importacao/DQA, configuracao/calendarios, motor de planeamento, simulador/CTP, APIs, snapshots/transacoes, trabalhos de fundo, indicadores e frontend. A ordem abaixo reflete risco funcional, nao tamanho dos ficheiros. Nao se propoem funcionalidades novas, mudancas de framework ou reescrita geral.

### Verificacao realizada

| Verificacao | Resultado |
| --- | --- |
| Backend completo, `pytest -q --durations=15` | 1741 passaram, 1 ignorado; 399,03 s |
| Frontend, `npm test` | 21 testes de logica + 107 testes de componentes passaram |
| Frontend, ESLint e TypeScript | Sem erros |
| Backend, Ruff | 3 ocorrencias: 2 ordenacoes de imports e 1 import inutilizado; nao sao a causa dos bugs funcionais |
| Navegador, aplicacao publicada | Hoje, Plano, Carga e capacidade, Entregas, Risco e Configuracao, a 1440 e 390 px; sem excecoes JavaScript nesse percurso |
| Navegador, falhas controladas | Revisao alterada, resposta HTTP 503, polling fora de ordem e gravacao de cenario |
| Persistencia isolada | Cenario obsoleto, reposicao por outra rota, apagar snapshot atual, retencao e plano sem procura |
| Motor, copia do plano real | Revisao 75, ISOP de 17.09, 95 operacoes, 557 segmentos; sem violacoes fisicas detetadas pelo validador atual |
| Motor, alteracao de OEE em copia | BFP079 para 0,50: 60,50 s; terminou em `timeout_with_baseline`, com os indicadores do plano anterior |

Passar a bateria existente nao prova ausencia de bugs: as reproducoes abaixo exercitam contratos que esses testes nao cobrem. O validador tambem tem uma lacuna, demonstrada em C01. Nao ficou provada otimalidade global do algoritmo nem ausencia de todas as inversoes possiveis de prioridade.

### Regras a preservar

- Manter as regras atuais de material/JIT, calendarios, operadores, setups, gemeas, subcontratacao e conservacao de quantidades.
- Manter a protecao integral dos lotes ja iniciados, segundo o corte diario atual. Nao introduzir fracionamento nem registo de execucao.
- Mostrar resultados e avisos dos cenarios. Robustez baixa ou atraso nao devem, por si so, esconder o resultado ou ser confundidos com impossibilidade fisica.
- Nao apresentar como executavel um resultado calculado com duracoes, procura ou recursos de outro cenario. A aprovacao de excecoes nao dispensa validade fisica.
- Nao aumentar timeouts nem reduzir limites de qualidade para disfarcar regressao.

## 2. Correcoes Prioritarias

### C01 - P1: Fallback de timeout conserva duracoes e prazos antigos

**Prova.** Numa reproducao sem lotes historicos, reduzir OEE de 0,66 para 0,33 exigia passar de 272,73 para 545,45 minutos. Apos timeout forcado, o simulador manteve 272,73 minutos, `physical_gate_passed=True` e permitiu aprovacao. Antecipar EDD de D3 para D0 manteve `lot.edd=3`: producao em D3 apareceu com OTD 100%, embora OTD-D fosse 0%. Na copia real, o timeout tambem devolveu o plano anterior apos mudar o OEE.

**Causa.** [simulator.py:143](/home/luis/projects/INCOMPOLINHO/backend/simulator/simulator.py:143) copia `baseline_result` e recalcula indicadores com dados novos, mas lotes antigos. [validation.py:227](/home/luis/projects/INCOMPOLINHO/backend/scheduler/validation.py:227) verifica duracao contra esses lotes; a cobertura da origem verifica quantidades, nao a coerencia completa de cadencia/prazos.

**Alteracoes planeadas.** Manter um candidato completo e validado para os inputs do cenario antes da procura de melhorias. No timeout, devolver apenas esse candidato, nunca reinterpretar o plano original como se tivesse sido recalculado. Validar lote/segmentos contra maquina efetiva, OEE, setup, outputs e marcos temporais da origem canonica; tratar separadamente os lotes historicos legitimamente congelados. Calcular OTD, OTD-D e gates a partir da mesma versao de lotes. Se nao existir candidato executavel, devolver diagnostico explicito sem publicar nem oferecer aplicacao de um falso candidato.

**Aceitacao.** Reproducoes acima devem falhar no codigo atual e passar apos a correcao. Abranger OEE, EDD, maquina alternativa, setup, gemeas e subcontratacao, com/sem historico. Identidade e plano ativo permanecem intactos se o calculo nao concluir.

### C02 - P1: CTP promete capacidade sem contar reinstalacoes da ferramenta

**Prova.** Num turno 07:00-15:00, outra ferramenta ocupa 10:00-12:40. Existem 320 minutos livres. Para 240 minutos de producao e setup de 60 minutos, o CTP devolveu `feasible=True` e 300 minutos necessarios. A interrupcao obriga a novo setup: sao necessarios 360 minutos, que nao cabem.

**Causa.** [_find_slot, ctp.py:350](/home/luis/projects/INCOMPOLINHO/backend/analytics/ctp.py:350) desconta um setup e acumula todas as janelas produtivas seguintes, mesmo depois de outra ferramenta ocupar a maquina. A verificacao de simultaneidade de recursos nao basta para garantir continuidade da campanha.

**Alteracoes planeadas.** Construir uma insercao concreta com os alocadores existentes de `scheduler/resources.py`; reservar maquina/ferramenta/equipa/operadores, considerar setups antes e depois da insercao e validar o plano combinado. Nao somar janelas desconexas como uma unica campanha. Manter o candidato exato associado a eventual aprovacao/aplicacao CTP.

**Aceitacao.** O exemplo deve ser inviavel. Testar interrupcao por outra ferramenta, mesma familia de setup, passagem de turno/dia, ausencia parcial de equipa, indisponibilidade e OEE da alternativa. Toda promessa viavel deve corresponder a uma insercao validavel, sem degradar silenciosamente compromissos existentes.

### C03 - P1: Importacao transforma erros Excel em procura zero

**Prova.** Uma celula de procura `-15600` foi substituida por `-15600x`, `#VALUE!` e uma formula sem valor calculado em cache. Nos tres casos, a procura total caiu de 26000 para 10400 sem erro de importacao; o TrustIndex manteve 95 e o mesmo numero de ocorrencias.

**Causa.** [_safe_int, isop_reader.py:115](/home/luis/projects/INCOMPOLINHO/backend/parser/isop_reader.py:115) devolve zero em conversoes invalidas; `load_workbook(data_only=True)` torna indistinguiveis formulas sem cache e celulas vazias. A DQA recebe dados ja convertidos, sem indicacao do erro original.

**Alteracoes planeadas.** Distinguir vazio permitido de valor invalido. Validar campos numericos com coordenada da celula, incluindo valores nao finitos e quantidades fracionarias. Inspecionar formulas quando falta valor calculado, sem implementar um motor de formulas. Rejeitar importacao com procura indeterminada usando o erro de carregamento existente; propagar avisos realmente recuperaveis para a DQA existente. Nao substituir valores desconhecidos por zero.

**Aceitacao.** Os tres ficheiros sinteticos nao podem ser aceites como tendo menor procura. Cobrir celulas vazias legitimas, numeros textuais suportados, erros Excel, formulas com/sem cache, WIP/backlog e ficheiro valido. O ISOP ativo fica intacto perante erro.

### C04 - P1: Apagar snapshot pode mudar o plano no proximo arranque

**Prova.** A rota de apagar aceitou remover o snapshot mais recente. `latest()` passou imediatamente da revisao 101 para 100, que e a selecao usada no arranque, embora a operacao de apagar nao seja uma reposicao de plano.

**Causa.** [plans.py:84](/home/luis/projects/INCOMPOLINHO/backend/api/plans.py:84) permite apagar qualquer registo. [store.py:146](/home/luis/projects/INCOMPOLINHO/backend/plans/store.py:146) e [copilot.py:63](/home/luis/projects/INCOMPOLINHO/backend/api/copilot.py:63) inferem o plano ativo pelo snapshot nao-cenario mais recente.

**Alteracoes planeadas.** Persistir explicitamente a referencia ao snapshot ativo, confirmada na mesma transacao de `commit_load`/`commit_mutation`. Separar guardar uma versao de tornar essa versao ativa. Proteger o snapshot ativo contra apagar/prune; a rota devolve conflito e a interface explica-o. Migrar bases existentes de forma aditiva, adotando uma vez o snapshot atualmente recuperavel. Manter compatibilidade com versoes historicas sem interpretar apagar como reposicao.

**Aceitacao.** Guardar, apagar historico, tentar apagar ativo e reiniciar nao alteram o plano ativo. Injetar falhas antes/depois do commit e testar a retencao C13. Nao pode existir referencia ativa pendente ou apagar a sua unica copia duravel.

### C05 - P1: Identidade dos cenarios nao e respeitada em todos os percursos

**Prova.** No navegador, depois de apresentar `candidate_id=audit-exact-preview`, “Guardar cenario” enviou apenas nome, nota e mutacoes. O backend voltou a simular. Em ambiente isolado, aplicar um cenario obsoleto pela rota de cenarios devolveu 409; repor o mesmo ID por `/plans/{id}/restore` devolveu 200 e substituiu os dados ativos.

**Causa.** [SimulatorPage.tsx:420](/home/luis/projects/INCOMPOLINHO/frontend/src/pages/SimulatorPage.tsx:420) e [endpoints.ts:313](/home/luis/projects/INCOMPOLINHO/frontend/src/api/endpoints.ts:313) nao enviam `candidate_id`, ja suportado em [scenarios.py:80](/home/luis/projects/INCOMPOLINHO/backend/api/scenarios.py:80). A rota generica [plans.py:51](/home/luis/projects/INCOMPOLINHO/backend/api/plans.py:51) aceita registos `source=scenario` sem as verificacoes de origem da rota especializada.

**Alteracoes planeadas.** Guardar o resultado e parametros efetivamente apresentados, enviando a identidade existente. Se o candidato expirou ou ficou obsoleto, pedir nova pre-visualizacao; nunca recalcular silenciosamente ao guardar. Recusar snapshots de tipo cenario na reposicao generica, ou encaminha-los pela mesma verificacao de origem e aplicacao exata. Manter a reposicao intencional de planos historicos normais.

**Aceitacao.** Guardar nao invoca o otimizador de novo e conserva o fingerprint do candidato. O mesmo cenario obsoleto e recusado por todas as rotas aplicaveis. Testar editar durante gravacao, duas sessoes e troca de ISOP; preservar edicoes de nome posteriores ao envio.

## 3. Frontend e Indicadores

### C06 - P2: Ecras conservam dados de revisoes anteriores

**Prova.** No navegador, Risco mostrou saude 91. Atualizar o snapshot para a revisao seguinte, cujo risco controlado era 12, manteve 91 e nao fez nova consulta de risco. A mesma dependencia apenas de montagem existe em Stock/Expedicao; Hoje depende do dia, nao da revisao.

**Causa.** [RiskPage.tsx:55](/home/luis/projects/INCOMPOLINHO/frontend/src/pages/RiskPage.tsx:55), [StockPage.tsx:84](/home/luis/projects/INCOMPOLINHO/frontend/src/pages/StockPage.tsx:84), [ExpeditionPage.tsx:50](/home/luis/projects/INCOMPOLINHO/frontend/src/pages/ExpeditionPage.tsx:50) e [ConsolePage.tsx:201](/home/luis/projects/INCOMPOLINHO/frontend/src/pages/ConsolePage.tsx:201) guardam copias locais sem identidade de plano. `/plan-view` atualiza o cabecalho, nao essas copias.

**Alteracoes planeadas.** Associar cada consulta analitica a `(dataset_id, plan_revision, parametros)`, subscrever essa identidade e descartar respostas de geracoes anteriores. Devolver identidade tambem nas respostas analiticas, obtidas de um estado capturado coerente. Nao misturar tres respostas de revisoes diferentes num `Promise.all`. Aplicar a mesma regra aos detalhes de SKU e aos resultados de robustez; preservar filtros e dia selecionado quando validos.

**Aceitacao.** Atualizar/recalcular/restaurar/trocar ISOP atualiza o ecrã aberto sem navegar para fora. Inverter a ordem de respostas de planos A/B nao volta a mostrar A. Testar StrictMode e desmontagem.

### C07 - P2: Atualizacao falhada e apresentada como sucesso

**Prova.** HTTP 503 em `/plan-view` produziu a mensagem “Dados atualizados”.

**Causa.** [useDataStore.ts:55](/home/luis/projects/INCOMPOLINHO/frontend/src/stores/useDataStore.ts:55) absorve erros salvo `strict:true`; [Shell.tsx:212](/home/luis/projects/INCOMPOLINHO/frontend/src/components/Shell.tsx:212) assume sucesso da chamada normal.

**Alteracoes planeadas.** Dar a `refreshAll` um resultado explicito ou usar o modo estrito nas acoes que anunciam sucesso. Conservar o snapshot anterior, mas apresentar a falha de atualizacao. Rever callers apos aplicacao: distinguir “aplicado no servidor, atualizacao do ecrã falhou” de “nao aplicado”, sem repetir a aplicacao.

**Aceitacao.** 503, timeout e falha de rede nunca geram confirmacao de dados atualizados nem apagam o rascunho. Perda de resposta de aplicacao reconcilia o recibo existente, sem segunda aplicacao automatica.

### C08 - P2: Polling de robustez pode regressar de concluido a em curso

**Prova.** Com respostas controladas no navegador, o segundo GET terminou o trabalho e mostrou “Executar”; o primeiro GET, atrasado, voltou a colocar o mesmo trabalho em `running`.

**Causa.** [RobustnessPanel.tsx:28](/home/luis/projects/INCOMPOLINHO/frontend/src/components/RobustnessPanel.tsx:28) usa `setInterval` com pedidos sobrepostos e sem descarte de respostas antigas. `cancel()` nao trata rejeicoes. O componente nao acompanha identidade/revisao do plano.

**Alteracoes planeadas.** Polling sequencial, geracao por trabalho e plano, aborto/descarte ao mudar de contexto e estados terminais monotónicos. Tratar erros de cancelar, incluindo corrida com conclusao. Desativar o inicio enquanto o POST estiver pendente e alinhar os controlos com as permissoes atuais de Consulta, sem alterar a politica de acesso.

**Aceitacao.** Resposta antiga nao reabre trabalho terminal nem substitui outro trabalho. Cobrir cancelamento concluido/recusado, rede lenta, desmontagem, Consulta e resultado de revisao anterior. Nunca modificar o plano como efeito destes testes.

### C09 - P2: Risco usa calendario diferente do planeador

**Prova.** Sabado aberto com 480 minutos de capacidade e 240 de carga apareceu com capacidade 0 e utilizacao 0 quando calculado pelo caminho sem configuracao. Com configuracao, os valores corretos foram 480 e 50%.

**Causa.** [_refresh_analytics, state.py:362](/home/luis/projects/INCOMPOLINHO/backend/copilot/state.py:362) chama `compute_risk` sem `config`, apesar de a API interna a suportar. O calculo cai nos defaults de dias/recursos.

**Alteracoes planeadas.** Passar `config=self.config` explicitamente e rever os restantes chamadores de capacidade/risco para usarem o mesmo calendario efetivo. Evitar uma assinatura ambigua entre `mc_cache` e `config`. Carga positiva com capacidade zero deve ser inconsistencia, nao simplesmente utilizacao zero.

**Aceitacao.** Comparar Gantt, capacidade e risco em sabados abertos, feriados, turnos curtos, maquina inativa e bloqueios parciais. Os mesmos minutos disponiveis devem resultar em todos os percursos.

### C10 - P2: Diagnosticos misturam encomendas e usam janelas temporais erradas

**Prova.** Hoje apresentou 69 dias de atraso para a referencia 1092262X100, enquanto o lote correspondente terminava 5 dias depois da entrega. O diagnostico escolhe o ultimo segmento de toda a referencia, incluindo procura de outras entregas. A previsao anunciada como “proximos N dias” percorre sempre D0..N-1; a consola tambem usa limites fixos D0..D5, independentemente do dia consultado. O texto de stock exclui a procura do proprio dia de rutura.

**Causa.** [action_items.py:41](/home/luis/projects/INCOMPOLINHO/backend/console/action_items.py:41), [expedition_today.py:16](/home/luis/projects/INCOMPOLINHO/backend/console/expedition_today.py:16), [action_items.py:191](/home/luis/projects/INCOMPOLINHO/backend/console/action_items.py:191) e [workforce_forecast.py:41](/home/luis/projects/INCOMPOLINHO/backend/analytics/workforce_forecast.py:41). `_find_fix` ainda afirma que capacidade diaria livre ou 420 minutos de noite “resolveriam”, sem validar todos os recursos.

**Alteracoes planeadas.** Obter ETA/cobertura para a encomenda concreta por acumulacao cronologica de stock e outputs, descontando entregas anteriores e respeitando gemeas/subcontratacao. Reutilizar as funcoes de producao por operacao e marcos de entrega existentes. Passar explicitamente o dia de referencia da consola/previsao, sem ocultar backlog ainda por cobrir. Somar procura por `day_idx <= stockout_day`, nao por posicao da lista. Apenas afirmar viabilidade de uma sugestao apos a verificacao corrigida em C02; caso contrario, identifica-la como hipotese a verificar.

**Aceitacao.** Uma encomenda de outubro nao recebe a ETA do ultimo lote de novembro. Testar varios clientes, stock inicial, backlog, gemeas, subcontratacao, dias negativos e mudanca de dia. A janela de equipa acompanha o dia atual/consultado e nao perde ausencias futuras.

### C11 - P2: Plano valido sem procura e tratado como ausencia de plano

**Prova.** Cancelar toda a procura por `/simulate` e `/simulate-apply` devolveu 200, OTD 100% e snapshot duravel com zero segmentos. Guardar esse mesmo plano devolveu 503, “Sem plano carregado”.

**Causa.** [plans.py:15](/home/luis/projects/INCOMPOLINHO/backend/api/plans.py:15), [state.py:299](/home/luis/projects/INCOMPOLINHO/backend/copilot/state.py:299), [state.py:337](/home/luis/projects/INCOMPOLINHO/backend/copilot/state.py:337) e outros guards equiparam lista de segmentos vazia a dados nao carregados.

**Alteracoes planeadas.** Distinguir dataset ausente, dataset valido sem procura e procura nao planeada. Permitir guardar/analisar/restaurar o caso legitimamente vazio; produzir indicadores vazios coerentes. Manter rejeicao de procura em falta e impedir movimentos quando nao ha lotes.

**Aceitacao.** Cancelar toda a procura, guardar, reiniciar, consultar e adicionar nova procura funciona sem 503 espurios. OTD zero por falta de planeamento nao pode ser convertido em OTD 100%.

## 4. Velocidade, Persistencia e Qualidade

### C12 - P2: Orcamento final insuficiente e analises repetidas

**Medicao.** No ensaio real de 60,50 s, `optimization` terminou em 55,14 s, mas o percurso exterior nao devolveu esse resultado e acabou no fallback. Foram observadas 4 fases de robustez, totalizando 24,01 s; construcao/planeamento somou 35,54 s, incluindo 13,45 s de normalizacao. Os tempos sao inclusivos: nao se devem somar entre si como fases independentes.

**Causa.** [frozen.py:249](/home/luis/projects/INCOMPOLINHO/backend/plans/frozen.py:249) partilha 60 s entre otimizacao residual e juncao/robustez/validacao final, sem reserva propria para todo esse fecho. [optimizer.py:415](/home/luis/projects/INCOMPOLINHO/backend/cpo/optimizer.py:415) e [_attach_robustness_score:4202](/home/luis/projects/INCOMPOLINHO/backend/cpo/optimizer.py:4202) repetem trabalho sobre candidatos em varios pontos. A reserva interna do otimizador nao garante a conclusao do percurso exterior.

**Alteracoes planeadas.** Reservar primeiro o custo do fecho exterior, incluindo juncao e validacao fisica, e limitar a procura ao restante. Robustez inconclusiva deve ficar explicitamente inconclusiva, sem destruir um candidato ja validado e sem herdar resultados de outro plano. Memoizar apenas calculos com igualdade de fingerprints de plano, dados, configuracao, modelo e seed. Reutilizar auditorias imutaveis; detetar repeticoes sem progresso na normalizacao. Manter cancelamento cooperativo ate ao fim.

**Aceitacao.** Repetir BFP079 indisponivel, PRM039 OEE 0,44, setup 1 h e ausencias Grandes A/B em copia. Registar p50/p95 por fase, quantidade de recalculos e latencia de GET durante trabalho. Um timeout nao pode cair no erro C01; nenhum ganho de tempo pode alterar quantidades, historia ou regras fisicas. Limites definitivos de desempenho devem partir de benchmarks repetidos, nao desta medicao unica.

### C13 - P2: Leitura integral dos snapshots e retencao incompleta

**Prova.** Com 38 planos, `list()` alocou 90,76 MiB para devolver metadados; a consulta so de metadados usou 0,01 MiB. `latest()` alocou 98,12 MiB. A consulta usada no prune de replaneamentos leu cerca de 109 MB de candidatos e alocou 119,77 MiB. A consulta equivalente das colunas necessarias usou 0,02 MiB. Em ensaio isolado, 25 commits acumularam snapshots automaticos para alem do limite de 20. A base observada tinha 31 snapshots automaticos.

**Causa.** [store.py:130](/home/luis/projects/INCOMPOLINHO/backend/plans/store.py:130) e `latest()` fazem `SELECT *`; o segundo carrega todos os registos antes de escolher um. [replan/jobs.py:275](/home/luis/projects/INCOMPOLINHO/backend/replan/jobs.py:275) repete leitura integral no prune, chamado tambem a cada atualizacao de progresso. `commit_mutation` nao executa a retencao usada em `persist_current_plan`. A lista de cenarios filtra `source` depois de limitar os 500 registos gerais, podendo esconder cenarios antigos ainda existentes.

**Alteracoes planeadas.** Selecionar apenas colunas de metadados; filtrar por tipo antes de `LIMIT`. Ler o snapshot ativo por ID depois de C04; percorrer historico em pequenos lotes apenas numa recuperacao explicita. Prune de trabalhos deve ler IDs/estado/worker, nao candidatos; retirar limpeza de historico do caminho de cada progresso quando nao necessaria. Aplicar a mesma retencao aos commits e carregamentos, protegendo referencias ativas e recuperacao. Nao eliminar recibos necessarios a idempotencia.

**Aceitacao.** Metadados nao crescem em memoria com o tamanho dos payloads. Testar mais de 500 snapshots sem esconder cenarios, limite de automaticos, rollback SQLite e recibos repetidos. Benchmarks separados para leitura, progresso e arranque; nao fazer VACUUM ou apagar historico de producao durante a correcao sem backup e politica explicita.

### C14 - P2: Calendarios de maquinas/ferramentas repetem trabalho quadraticamente

**Prova.** Um ensaio identico com 20/100/200/400 entradas de maquina demorou 2,66/53,66/209,09/806,40 ms. A duplicacao de 200 para 400 aproximou-se de quatro vezes o custo. Esta medicao nao se aplica ao caminho de operadores, que foi aproximadamente linear no ensaio.

**Causa.** [_project_intervals, calendars.py:145](/home/luis/projects/INCOMPOLINHO/backend/transform/calendars.py:145) chama `_timeline_days(entries, ...)` dentro do ciclo de cada entrada; o helper normaliza novamente toda a colecao. Datas muito distantes tambem materializam dias intermédios desnecessarios.

**Alteracoes planeadas.** Normalizar entradas e construir indice temporal uma vez por reconstrucao; projetar apenas intersecoes relevantes. Conservar intervalos canonicos futuros/sem fim, expandindo-os quando o horizonte efetivo o exigir, sem criar bloqueios gigantes nem os perder. Reutilizar uniao de intervalos e evitar varrer todos os contribuidores para cada fragmento quando um indice basta.

**Aceitacao.** Resultado semanticamente identico para sobreposicoes, remocao de ausencias, turnos alterados, meia-noite, timezone e indisponibilidade sem fim alem do horizonte. Medir 20/100/400/1000 entradas; crescimento nao quadratico no caso reproduzido. Nunca abreviar calendarios de forma que permita produzir durante um bloqueio.

### C15 - P2: Validacao numerica diverge entre rotas e configuracao

**Prova.** Movimento manual aceitou `target_day=1.9` como 1 e `true` como 1. A normalizacao de ausencias carregadas aceitou `count=3.9` como 3 e `true` como 1. O helper de adicionar ausencia pela API ja e mais estrito: o problema nao esta em todos os percursos.

**Causa.** [_request_values, manual_plan.py:36](/home/luis/projects/INCOMPOLINHO/backend/api/manual_plan.py:36), [_normalize_unavailability, loader.py:119](/home/luis/projects/INCOMPOLINHO/backend/config/loader.py:119), conversao de equipas em [replan.py:448](/home/luis/projects/INCOMPOLINHO/backend/api/replan.py:448) e casts semelhantes antes da validacao. Ha tambem `bool(...)` sobre aprovacoes de corpos nao tipados, onde a string `"false"` e verdadeira.

**Alteracoes planeadas.** Reutilizar validadores canonicos estritos para inteiros finitos, revisoes, minutos, pessoas e flags de aprovacao. Validar antes de converter; manter strings inteiras suportadas, sem truncar fracoes. Partilhar a validacao entre YAML, snapshot, APIs antigas e replaneamento, mantendo aliases intencionais.

**Aceitacao.** Matriz com bool, fracao, NaN, infinito, string inteira, string decimal, vazio, negativo e limites. Valores rejeitados nao iniciam calculo nem incrementam revisao. `"false"` nunca autoriza excecoes.

### C16 - P2: Regras podem ter IDs repetidos e perder consistencia na gravacao

**Prova.** Criar duas regras, apagar a primeira e criar outra produziu dois IDs `rule_2`. Apagar uma dessas regras removeu as duas.

**Causa.** [state.py:385](/home/luis/projects/INCOMPOLINHO/backend/copilot/state.py:385) usa `len(rules)+1`; `_save_rules` escreve diretamente o ficheiro apos alterar a lista em memoria. Os executores de adicionar/remover regra atualizam revisao fora do coordenador comum.

**Alteracoes planeadas.** IDs realmente unicos para novas regras, preservando os existentes. Detetar duplicados legados e migrar explicitamente sem apagar conteudo. Preparar a lista numa copia; gravacao atomica/duravel antes de publicar memoria e revisao. Coordenar essas escritas com o mecanismo transacional existente, incluindo o ficheiro de regras na recuperacao necessaria; nao as deixar fora da concorrencia por serem comandos do Copilot.

**Aceitacao.** Sequencia criar/apagar/criar mantem IDs distintos; remover um ID remove exatamente uma regra. Simular falha de escrita/rename, duas sessoes e reinicio, mantendo conteudo e revisao coerentes. Nao mudar a semantica das regras nem transformar preferencias em novas restricoes do motor.

## 5. Ordem de Execucao e Validacao

1. **Fixar reproducoes.** Converter os ensaios isolados em testes permanentes que falhem antes da correcao. Manter fixtures pequenas e reservar o ISOP real anonimizado/copiado para benchmarks. Registar fingerprints dos inputs.
2. **Corrigir resultados/dados incorretos.** C01, C02 e C03; preparar o fecho temporal de C12 com C01. Nao publicar uma correcao que apenas melhore mensagens ou habilite botoes.
3. **Proteger estado duravel e candidatos.** C04, C05, C11 e C16, seguidos da retencao C13. Migracoes aditivas e compatibilidade de snapshots, sem substituir automaticamente o plano ativo.
4. **Coerencia do frontend e indicadores.** C06-C10 e C15, usando os mesmos contratos de identidade/validacao. Sem redesign, novas paginas ou novos fluxos de negocio.
5. **Eliminar custo comprovadamente redundante.** C12-C14. Medir antes/depois no mesmo ambiente, com resultado equivalente ou melhoria validada; nao otimizar apenas pela contagem de linhas.
6. **Regressao completa e publicacao futura.** Reexecutar backend/frontend, TypeScript/lint, ensaios de falha e navegador. So depois, backup consistente de YAML/regras/SQLite e publicacao com procedimento de rollback. Esta auditoria nao executa essa publicacao.

### Matriz minima de regressao transversal

| Percurso | Invariantes/aceitacao |
| --- | --- |
| BFP079 indisponivel 12-18/10; entregas 16/10 e novembro | Explicar atraso por recursos/material; testar encaixe legal na PRM031 em 19-23/10 e ordem de prioridades; ausencia de capacidade legal nao pode ser inferida apenas de uma barra vazia |
| Grandes A/B: 6/5 operadores, ausencia de 3 em cada equipa em 21-27/09 | Com um operador por maquina, pico maximo 3/2 no turno respetivo; remover/aplicar/replanear/reiniciar elimina o bloqueio retirado sem apagar os restantes |
| PRM039 OEE 0,44; setup 1 h; alternativa e gemeas | Duracao e setups coerentes com destino e fonte; mesmos outputs e quantidades; nenhuma aprovacao contorna conflito fisico |
| Pre-visualizar A, editar B, guardar/aplicar | Apenas o candidato apresentado e identificado pode ser guardado/aplicado; respostas antigas sao descartadas |
| Aplicar, perder resposta, repetir, reiniciar | Mesmo recibo e efeito unico; configuracao e plano nunca ficam de revisoes diferentes |
| Duas sessoes, atualizacao/ISOP durante calculo | Conflito explicito preserva rascunho; nenhuma escrita aceite desaparece silenciosamente |
| Cancelar durante solver, fecho, aplicacao e polling | Candidato incompleto nao se publica; conclusao duravel nao regressa a em curso/cancelamento; frontend reconcilia estado real |
| Calendarios combinados | Ordem equivalente quando as operacoes comutam; horas extra nao removem bloqueios; adicionar/remover ausencia nao duplica descontos |
| Falhas SQLite/YAML/recibo/HTTP | Estado anterior intacto ou operacao concluida recuperavel, nunca mistura nem mensagem falsa de sucesso |
| Frontend 390/1440 px, StrictMode e Consulta | Controlos acessiveis, nenhuma sobreposicao incoerente, nenhum resultado obsoleto, nenhuma aplicacao indevida |
| Sem procura e fora do horizonte inicial | Plano vazio legitimo continua consultavel; extensao conserva procura/calendarios; falta de producao continua detetada |

### Limites e Pontos Nao Confirmados

- O plano real examinado nao apresentou violacoes fisicas no validador atual; isso nao constitui prova de otimalidade ou de completude desse validador. As anomalias brutas de prioridade nao devem ser confundidas com inversoes evitaveis: estas precisam de prova de encaixe legal.
- As escritas/aplicacoes no browser foram respostas controladas; as aplicacoes reais foram feitas apenas nas fixtures isoladas. Nao se ensaiou uma alteracao de producao em nome do utilizador.
- Os tempos observados sao medicoes locais, nao uma media de producao. Falta uma distribuicao repetida de latencia sob concorrencia antes de fixar metas p95.
- Nao se reproduziu esgotamento de memoria na leitura de XLSX muito expandido, nem todos os pontos de falha possiveis entre escrita e reinicio. Devem entrar nos testes de robustez de importacao/transacoes, sem apresentar risco teorico como incidente confirmado.
- O modo Consulta e uma protecao funcional, nao autenticacao; adicionar autenticacao nao pertence a este plano de correcoes. A reversao apos reinicio tem limitacoes documentadas; nao se propoe aqui um novo historico de undo.
- Os tres avisos Ruff podem ser eliminados ao tocar nos respetivos modulos. Nao justificam refatoracao geral nem explicam a lentidao medida.

**Conclusao:** os problemas confirmados concentram-se em identidade/coerencia de resultados, contratos incompletos entre percursos e trabalho repetido. A correcao deve unificar esses contratos e torna-los verificaveis, mantendo a experiencia e as regras existentes.
