# Correcoes C01-C16: implementacao e verificacao

Data: 23 de setembro de 2026.

## Estado da entrega

Implementacao feita em `/home/luis/projects/INCOMPOLINHO-corrections`, a partir
da arvore original, incluindo as alteracoes nao commitadas. Baseline preservada
em `/home/luis/projects/INCOMPOLINHO-corrections-baseline`.

**Publicado em 23/09/2026, com verificacao publica concluida as 08:10 UTC.**
Backend/frontend entregues em conjunto, mantendo portas, tunel e endereco:
https://inside-arranged-county-wing.trycloudflare.com

Depois da autorizacao expressa do utilizador, foram corrigidas apenas as datas
internas de material de cinco lotes e dos seus 11 segmentos associados. Nao houve
recalculo nem alteracao das maquinas, horarios, quantidades, entregas ou configuracao.
A revisao passou de 75 para 76; o mesmo dataset conserva 95 operacoes, 202 lotes e
557 segmentos. OTD 92,6%, OTD-D 98,1% e 15 entregas atrasadas mantiveram-se.

As aplicacoes/importacoes de teste ocorreram exclusivamente na instancia isolada.
Nao foram copiados os seus ficheiros de configuracao nem os dados de ensaio.
Em producao, a verificacao no navegador foi apenas de leitura.

## Matriz C01-C16

Todos os itens seguintes foram implementados, testados na copia isolada e
integrados na publicacao conjunta. As provas e limites dos ensaios constam abaixo.

| ID | Causa eliminada / implementacao | Prova permanente e percurso |
| --- | --- | --- |
| C01 | Retencao apenas de candidato completo, combinado com historico e validado; sem fallback de lotes antigos com inputs novos. `scheduler/canonical.py`, `plans/frozen.py`, `simulator/simulator.py`. | `test_audit_timeout_regressions.py`, `test_frozen_planning.py`; OEE, prazos, setup, quantidades, historico e cancelamento. |
| C02 | CTP constroi `rush_order` pelo pipeline partilhado, verifica a quantidade prometida e os compromissos anteriores, conserva o candidato exato. | `test_audit_ctp_regressions.py`, `test_candidate_api.py`; verificacao/aplicacao real no browser, fingerprint persistido igual ao aprovado. |
| C03 | Numeros invalidos e formulas sem cache deixam de se converter em zero; erros/avisos conservam folha, celula e campo ate a DQA. | `test_audit_input_regressions.py`, `test_parser.py`; ficheiro invalido N6 recusado no browser sem mudar o plano, ficheiro valido importado. |
| C04 | `plan_runtime` seleciona explicitamente snapshot ativo/revisao; confirmacao atomica com snapshot e recibo; FK protege eliminacao. | `test_audit_persistence_regressions.py`, `test_plan_transactions.py`, `test_plans.py`; reinicio real preserva revisao, configuracao, lotes e segmentos. |
| C05 | Guardar envia e consome `candidate_id`; sem recalc silencioso; reposicao generica recusa cenarios; identidade/revisao obsoleta da 409. | `test_scenario_identity.py`, `SimulatorPage.test.tsx`; guardar no browser conservou o candidato e nao alterou o plano. |
| C06 | Consultas capturam estado coerente; headers `X-Dataset-Id`/`X-Plan-Revision`, 409 se esperado diverge; frontend descarta respostas antigas. | `test_analytic_identity.py`, `ConsolePage.test.tsx`, `RiskPage.test.tsx`, `planState.test.tsx`; navegacao real a 390/1440 px. |
| C07 | `refreshAll` retorna `updated`, `superseded` ou `failed`; falha preserva snapshot; aplicacao confirmada distingue falha de refresh; ID estavel recupera recibo. | `loadRefresh.test.tsx`, `planState.test.tsx`, transacoes; 503 no browser nao anunciou sucesso; perda real de resposta apos commit CTP nao duplicou procura. |
| C08 | Polling sequencial, timeout finito, geracoes por trabalho/revisao, cancelamento reconciliado e duplo inicio impedido. | `RobustnessPanel.test.tsx`, `ConfigPage.test.tsx`, testes de trabalhos; cancelamento real durante calculo e modo Consulta sem POST de escrita. |
| C09 | Risco/capacidade usam configuracao efetiva e calendarios do motor; carga com capacidade zero tem utilizacao indefinida e estado critico. | `test_audit_analytics_regressions.py`, `test_capacity.py`, `test_risk.py`; sabado aberto, maquina fechada e estado sem procura. |
| C10 | ETA por alocacao cronologica da encomenda, nao ultimo lote da referencia; stock/entregas/gemeas/subcontratacao preservados; janelas avancam com dia; hipoteses identificadas. | `test_audit_analytics_regressions.py`, `test_audit_demand_trace_regressions.py`, `test_console.py`; mutacoes sincronizam rastreabilidade e mantem quantidades arredondadas. |
| C11 | Dataset ausente, procura vazia e procura por planear sao distintos; plano vazio legitimo pode guardar/restaurar/consultar e voltar a receber procura. | `test_audit_empty_regressions.py`; cancelar tudo, persistir, restaurar e adicionar procura sem falso OTD zero/503. |
| C12 | Deadline exterior e reserva de fecho; ultimo candidato completo; robustez nao concluida sem percentagem herdada; cache limitada a execucao/identidade; ciclos sem progresso interrompidos. | `test_planning_control.py`, `test_frozen_planning.py`, `test_cpo.py`; 40 execucoes reais abaixo de 53 s; bateria real de robustez contabilizada separadamente. |
| C13 | SELECT de metadados, filtro antes de LIMIT, leitura direta do ativo, prune de trabalhos sem payload; retencao 20 automaticos mais protegidos, sem apagar recibos/manuais/cenarios. | `test_audit_persistence_regressions.py`; mais de 500 snapshots, payloads grandes, retencao e recibos; benchmarks antes/depois. |
| C14 | Normalizacao unica e projecao indexada de intersecoes; fontes futuras/sem fim preservadas; overlays uma vez; remocao reconstroi capacidade base. | `test_audit_calendar_regressions.py`, `test_calendars.py`, `test_operator_absence_lifecycle.py`; 3/2 -> 4 maquinas apos remocao e reinicio; formulario mobile verificado. |
| C15 | Validadores comuns antes de casts em config/YAML, simulador, movimentos, revisoes e APIs; inteiros finitos estritos, booleanos reais nas aprovacoes. | `test_audit_input_regressions.py`, `test_api_validation.py`, `test_manual_move.py`; bool, fracao, NaN, infinito, strings e limites. |
| C16 | UUID para novas regras, UUID deterministico nos duplicados; coordenador unico e journal recuperavel de YAML/JSON; memoria so depois do commit duravel. | `test_plan_transactions.py`, `test_plans.py`; criar/apagar/criar, migracao sem perda e falhas antes/depois de ficheiros, snapshot, ponteiro e recibo. |

## Correcoes adicionais dentro dos contratos auditados

- Reservas de lotes iniciados deixam de criar feriados artificiais que alteravam
  datas de material. Reservam tambem equipas de setup e montagem mantida nas
  continuacoes, sem duplicar operadores no plano final.
- Retirar setup redundante mantem o intervalo produtivo original, evitando
  desloca-lo para um periodo onde os operadores ja estavam ocupados.
- Projecao de calendarios respeita o deslocamento temporario do horizonte;
  adicionar buffer deixa de abrir antecipadamente uma indisponibilidade.
- Aviso de falta de equipas passa a contar setups realmente simultaneos, e nao
  tres setups consecutivos numa janela de duas horas.
- ETA CTP ignora a cauda nao utilizada do mesmo lote, mantendo a regra de lote
  completo para subcontratacao.
- Diagnostico canonico identifica cada lote com marcos incoerentes, em vez de
  atribuir todos os erros ao primeiro lote do plano.

## Testes automatizados

- Backend final: **1808 passaram, 1 ignorado**, em 388,87 s. O caso ignorado por
  omissao e o ensaio longo optativo de 151 segundos: **passou separadamente**, em
  151,81 s. Total: **1809 casos distintos passaram**, incluindo o optativo.
  Regressao final focada de validacao/historico: 60 passaram.
- Migracao autorizada: mais **9 testes permanentes passaram**, incluindo recusa
  de alteracoes nao autorizadas, conflitos fisicos, datas inesperadas, identidade
  obsoleta, falha de commit e repeticao idempotente. Bloco final de persistencia,
  transacoes, timeout e migracao: **51 passaram**. Sao 1818 casos backend distintos
  aprovados no conjunto das execucoes, nao uma nova execucao integral unica.
- Frontend final: **21 testes de logica + 116 testes de componentes passaram**.
- Ruff e ESLint: sem erros. TypeScript e build Vite: passaram.
- O runner Python emite um aviso de depreciacao Starlette/httpx ja existente;
  nao foi feita uma atualizacao de dependencias fora do ambito das correcoes.
- Vite conserva aviso de bundle de 526,18 kB (>500 kB). O limite nao foi aumentado
  para esconder o aviso; nao foi introduzido redesign ou refatoracao geral.
- Falhas ensaiadas: SQLITE_BUSY/commit, ficheiro/rename, snapshot, ponteiro ativo,
  recibo e perda de resposta HTTP; recuperacao conserva estado anterior ou commit
  recuperavel, sem confirmar parcialmente a operacao.

## Navegador real

Chromium, React StrictMode, interfaces reais e backend isolado:

1. PRM039 0,66 -> 0,44: guardar, rever avisos, aprovar, aplicar e recarregar.
   Pre-visualizacao em 57,742 s; 47 GETs de saude durante o calculo, maximo 115,4 ms.
2. Grandes A/B 6/5: adicionar ausencia de 3 em cada turno, guardar/aplicar, retirar
   ambas e guardar/aplicar novamente. Picos medidos: 4/4 -> 3/2 -> 4/4. Nenhuma
   falta de quantidade/violacao fisica. Ensaio UI usa semana futura 19-25/10 para
   nao alterar lotes iniciados; teste permanente cobre especificamente 21-27/09.
3. Simular, guardar candidato, editar parametros: resultado anterior invalidado.
   CTP 10 -> 20 pecas: nova verificacao obrigatoria. Depois do commit, resposta HTTP
   substituida por 503; repeticao com mesmo ID recuperou recibo, uma unica revisao
   e procura adicionada uma unica vez. Fingerprint do snapshot igual ao candidato.
4. ISOP invalido: erro com N6, plano anterior intacto. ISOP valido: importacao e
   aplicacao reais sem violacao fisica ou procura em falta.
5. Hoje, Plano, Carga e capacidade, Entregas, Risco e Configuracao a 390/1440 px,
   esperando dados carregados antes das capturas. Sem excecoes JavaScript.
6. Falha de refresh, conflito 409 e Consulta: mensagem verdadeira, rascunho
   preservado, nenhum retry automatico nem POST indevido de alteracao.
7. Reinicio real depois de remover ausencias: revisao 83 permaneceu 83; identidade,
   configuracao, segmentos e lotes iguais. Apenas metadados informativos de
   restauracao foram acrescentados ao descritor do dataset.
8. Robustez intensiva com POST atrasado e GET retido: inicio desativado durante
   envio, cancelamento confirmado, resposta antiga libertada depois. O ecra nao
   regressou a running; Consulta nao iniciou trabalhos; plano intacto.

Relatorios/capturas: `/tmp/incompolinho-corrections-browser-*.json` e
`/tmp/incompolinho-corrections-*.png`. Harness permanente: `scripts/audit_browser.mjs`.
Requer Playwright instalado; `PLAYWRIGHT_MODULE` e `PLAYWRIGHT_CHROMIUM_PATH`
permitem indicar a instalacao de teste. O endereco de escrita e fixo na instancia
isolada `http://127.0.0.1:53970`.

## Desempenho

Copia da revisao 75, ISOP 17.09, 95 operacoes/557 segmentos. Inputs iguais,
PYTHONHASHSEED=0, corte diario fixado no ensaio; nunca dados vivos. p95 e o maior
valor em dez medicoes (nearest rank). Tempos sao locais, nao medias de producao.

| Cenario, 10 repeticoes cada | p50 | p95 | Pico RSS | Resultado |
| --- | ---: | ---: | ---: | --- |
| PRM039 OEE 0,44 | 52,435 s | 52,601 s | 155,12 MiB | 10 candidatos validos |
| BFP079 indisponivel 12-18/10 | 48,970 s | 49,506 s | 156,46 MiB | 10 candidatos validos |
| Grandes A/B -3 em 21-27/09 | 48,376 s | 48,651 s | 159,36 MiB | 10 candidatos validos |
| BFP079 setup 1 hora | 49,665 s | 52,328 s | 156,84 MiB | 10 candidatos validos |

Zero violacoes fisicas e origem intacta nas 40 execucoes; um fingerprint de
resultado por serie. Para operadores, o corte foi fixado antes da semana para
ensaiar a introducao da ausencia; preservacao do historico tem testes separados.
Os tempos de fases inclusivas nao devem ser somados. O ensaio adicional BFP079
confirmou uma bateria efetiva de robustez, distinguindo-a de callbacks sem calculo.

Cancelamento real: sinal aos 3 s, `PlanningCancelled` aos 4,652 s, sem candidato
aplicado nem alteracao da origem. Latencia apos o sinal: 1,652 s.

| Operacao, 10 repeticoes | Antes p50 / p95 | Depois p50 / p95 |
| --- | ---: | ---: |
| Listagem de planos | 187,79 / 229,94 ms | 0,124 / 0,338 ms |
| Leitura usada no arranque | 181,50 / 232,34 ms | 83,06 / 94,70 ms |
| Calendario, 20 entradas | 3,62 / 6,95 ms | 0,82 / 1,04 ms |
| Calendario, 100 entradas | 77,05 / 108,28 ms | 1,48 / 2,10 ms |
| Calendario, 400 entradas | 1447,43 / 2030,93 ms | 6,50 / 12,46 ms |
| Calendario, 1000 entradas | 8257,99 / 10591,06 ms | 17,03 / 31,98 ms |

Pico de alocacoes da listagem: 90,76 -> 0,035 MiB; leitura de arranque:
98,09 -> 7,80 MiB. Projecao de 1000 entradas: 0,73 -> 1,11 MiB, uma troca
explicita por indices, sem o crescimento quadratico de tempo reproduzido.

Comparacao do motor antigo: a auditoria registou 60,50 s e fallback incorreto com
inputs novos. Nao e uma distribuicao equivalente aos cenarios acima; nao se
apresenta como p50/p95 comparavel nem como ganho de velocidade percentual.

BFP079 com entrega 16/10: no ensaio adicional termina em 20/10, apos retomar em
19/10, antes das producoes para novembro. A alternativa PRM039 foi usada; nao e
obrigatorio usar PRM031 quando outra atribuicao legal e mais favoravel. Nao houve
producao da ferramenta durante a semana bloqueada. Isto nao prova otimalidade
global do algoritmo ou ausencia de todos os conflitos possiveis.

## Migracao Autorizada

A validacao da copia do plano publico identifica apenas divergencias de
`output_milestones.material_release_day` nos seguintes lotes:

| Lote | Guardado -> canonico | Primeiro dia de producao |
| --- | --- | ---: |
| LOT_BFP082_PRM019_1092262X100_8 | -2 -> 1 | 5 |
| LOT_BFP112_PRM039_1197914X050_8 | -2 -> 1 | 5 |
| LOT_TWIN_JTE004_11, ambos outputs | -1 -> 4 | 7 |
| LOT_JDE002_PRM042_TP042173-0040-1_11 | -1 -> 4 | 5 |
| LOT_HAN002_PRM043_CF589MMA1A02.20_19 | -1 -> 4 | 5 |

Origem: a implementacao antiga reservava dias passados como feriados temporarios,
o que alterava o calculo de datas de material. Os horarios observados respeitam
as datas canonicas, mas os metadados guardados nao. A nova validacao nao os ignora.

Evidencia inicial: `/tmp/incompolinho-corrections-release-preflight-latest.json`.
O utilizador autorizou explicitamente a correcao limitada. O script
`scripts/repair_material_metadata.py` verifica identidade e marcos canonicos,
recusa diferencas noutros campos e valida o plano inteiro antes de gravar.
As datas vazias das continuacoes permanecem vazias. Os novos campos do modelo
recebem apenas defaults, sem alterar qualquer input existente.

A gravacao usa snapshot novo, ponteiro ativo e recibo na mesma transacao. O
snapshot anterior permanece no historico. Robustez nao recalculada fica por
avaliar, sem reutilizar uma percentagem com outro fingerprint. Dois arranques da
copia migrada conservaram a revisao 76; o arranque publico confirmou o mesmo.
Nenhuma chamada ao otimizador foi usada nesta migracao.

Fingerprint da execucao, excluindo apenas as datas internas autorizadas, identico
antes/depois e no estado servido pela API:
`98de12dad54e039dbcea0729054ffd1a55e240a61b00ab626b6acf3c55152285`.
Validacao final: zero conflitos fisicos; gates fisico, quantidade e material
aprovados. Avisos de entregas e robustez continuam visiveis.

## Integracao e Publicacao

`scripts/audit_release_manifest.mjs` compara baseline, copia editada e arvore
publica por SHA-256. A comparacao imediatamente antes da integracao confirmou
120 ficheiros alterados, zero conflitos. Cada ficheiro foi novamente verificado
antes/depois da copia. Inputs de build e dependencias eram iguais nas tres arvores.
As alteracoes anteriores do utilizador foram preservadas.

1. Confirmada ausencia de trabalhos em calculo e de journals pendentes.
2. Parados apenas os servicos backend/frontend; cloudflared permaneceu com o
   mesmo processo. Backup completo verificado com gzip, incluindo codigo sujo,
   configuracao e regras; backup SQLite das quatro bases com integrity_check OK.
3. Integrados apenas os ficheiros do manifesto. Migracao dos cinco lotes aplicada
   com guardas da revisao 75 e fingerprint original. Sem copia de dados de teste.
4. Backend iniciado e validado antes de reabrir o frontend. Ambas as unidades
   ativas, sem reinicios inesperados; portas 8010/53868 e tunel preservados.
5. Chromium pelo URL publico: Hoje, Plano, Carga e capacidade, Entregas, Risco e
   Configuracao a 1440/390 px. Zero excecoes JavaScript, erros API ou pedidos de
   escrita. Identidade, segmentos, lotes, configuracao, mutacoes e score iguais
   antes/depois da navegacao. Capturas inspecionadas.

Backup e comprovativo da migracao:
`/home/luis/projects/INCOMPOLINHO-backups/20260923T0810-release/`.
Inclui `before.tar.gz`, bases SQLite verificadas, unidades dos servicos, manifesto,
`material-repair.json` e provas de navegador. Configuracao YAML e regras JSON
mantiveram os hashes originais. Nao foi necessario rollback.

Harness de verificacao publica: `scripts/audit_release_readonly.mjs`, que bloqueia
qualquer escrita API. Relatorios originais:
`/tmp/incompolinho-release-rehearsal-browser.json` e
`/tmp/incompolinho-release-public-browser.json`.
Os ensaios cobrem os casos descritos; nao demonstram ausencia absoluta de bugs
nem otimalidade global do algoritmo.

## Reexecutar verificacoes

Na arvore isolada, sem apontar os processos de teste para os dados publicos:

```bash
.venv/bin/pytest -q --durations=15
INCOMPOL_LONG_LOAD_TEST=1 .venv/bin/pytest -q 'tests/test_load_jobs.py::test_http_remains_responsive_during_slow_calculation[151]'
.venv/bin/ruff check backend tests scripts
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

Os benchmarks aceitam `--database` exclusivamente com uma copia consistente:
`scripts/benchmark_corrections.py` e `scripts/benchmark_storage_calendars.py`.
O segundo inicializa/migra a copia para medir a leitura, nunca deve receber uma
base publica. A comparacao anterior usa o codigo da baseline e outra copia.
