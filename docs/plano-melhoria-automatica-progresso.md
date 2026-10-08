# Progresso: plano de melhoria automática do planeamento

Plano: `docs/plano-melhoria-automatica-planeamento.md`.

## Ambiente Inicial (Registo Histórico)

- Cópia isolada (git worktree): `/home/luis/projects/INCOMPOLINHO-melhoria`,
  ramo `claude/melhoria-automatica-planeamento`, criado a partir de `4950a9e`
  com as 225 alterações não commitadas da árvore principal copiadas por rsync.
- `.venv`, `node_modules` e `frontend/node_modules` são symlinks para a árvore
  principal (não editar dependências a partir daqui).
- A árvore principal `/home/luis/projects/INCOMPOLINHO` está a ser servida
  (Vite :53868, uvicorn :8010) — **não editar** (plano §10.2).
- §10.3 (publicação) fica para aprovação do Luís.

## Estado dos Blocos (Atualizado Em 02/10/2026)

As iterações abaixo conservam o registo original. A tabela inclui as
publicações e verificações posteriores documentadas em
`docs/causa-raiz-planeamento-2026-10-01.md`; não significa que os horários
históricos do plano ativo tenham sido reconstruídos.

| # | Bloco | Estado |
|---|-------|--------|
| 1 | Baseline funcional (pytest completo) | feito — 1874 passed, 1 skipped |
| 2 | Contrato: serviço por encomenda, marcos de subcontratação, setups físicos, assinatura física, desempate (§4) | feito |
| 3 | Baseline de desempenho (ISOP reais, 10 repetições) | feito — p50 48,35 s, p95 48,8 s, RSS ~148 MiB |
| 4 | Retirar excepção de atraso no fim de campanha + exclusão do audit (§3.2, §6.3) | publicado; retirado também o filtro que confundia fim do lote com perda de entrega, com quatro regressões permanentes |
| 5 | Adaptar geradores ao avaliador comum (gap_filling, priority_normalization, alternative_repair, campaign_tail, shift_exchange) | excepções retiradas (iteração 6); ligação ao coordenador no bloco 6 |
| 6 | Coordenador: ciclo único, invalidação, relatório `improvement_report` (§5, §7.1) | publicado e verificado; cache corrigida (secção 22), pesquisa truncada explícita; secção 32: prioridade, cauda e trocas de turno usam também o contexto protegido completo |
| 7 | Integração scheduler/CPO; remover inferência por texto de warnings (§3.3, §6.2) | implementado e publicado; percurso com proteção histórica avalia o plano completo |
| 8 | Percursos: recalcular, config, libertação, simulador, movimento manual; `gate_report` (§6.5, §7.2) | publicado; relatório completo e resumo conservados até aplicação, reversão e reinício (secção 23), com validação real de resultados concluído/parcial; plano público não substituído |
| 9 | Restauro sem optimização oculta (§6.6) + docs de invariantes | publicado e verificado; secção 31 fecha recálculo por truthiness e revisão pública nula, com 83 regressões e reposição real no navegador |
| 10 | Frontend: tipos e mensagens existentes (§6.5) | publicado; pesquisa parcial verificada também no modal de movimento real isolado a 390/1440 px; 152 testes frontend passaram |
| 11 | Fixtures BFP112/BFP082/BFP079/ausências A/B (§8.1) + melhorias encadeadas (§8.2) | parcial: regressões genéricas e ensaios reais registados; reconstrução dos horários históricos depende de esclarecer se setembro é simulação ou produção realizada |
| 12 | Verificação completa: pytest, npm test/lint/build, ruff, diff --check | último bloco publicado (secção 36): 2507 backend completos passaram, dois ignorados; 212 frontend, lint, TypeScript/build e Ruff passaram. Após integração: 211 backend e 212 frontend; seis páginas públicas a 390/1440 px sem erros ou escritas. Plano ativo 89 intacto. Não conclui a auditoria integral. |

Últimos blocos (01/10): retirado o filtro que confundia o fim do lote com
perda de entrega (secção 10). A secção 11 documenta outro defeito reproduzido:
uma pesquisa truncada apresentava-se como concluída ou como impossibilidade
física. A correção comunica limites explicitamente e mostra pesquisa parcial
na interface existente. Não altera o contrato ou a hierarquia de objetivos.
O plano público continua na revisão 89; os movimentos e a alteração de OEE
dos ensaios pertencem só à instância isolada. O movimento manual ensaiado não
devolvia o resumo `improvement`: a secção 12 reproduz e corrige a divergência
no fecho desse percurso, usando o candidato completo e o contrato comum.
O novo ensaio apresentou o relatório, encontrou antecipações e conservou a
hora pedida e os 202 lotes. A tabela não conclui toda a auditoria.

Bloco adicional publicado (secção 13): montagem anterior centralizada para
movimentos e limpeza automática; preparação repartida conserva-se ou retira-se
integralmente. Cinco execuções falharam antes, 186 regressões focadas e 1997
backend completos passaram, mais 152 frontend. A fixture genérica foi aplicada
no navegador a 390/1440 px, com início às 08:30 sem novo setup nem intervalo.
As dez repetições na cópia do ISOP passaram. Após integração, 234 regressões
backend e seis páginas públicas a 390/1440 px passaram; o plano ativo ficou intacto.

Bloco seguinte publicado e verificado (02/10, secção 14): falhas de
pesquisa manual deixam de provar falsamente impossibilidade global; os
impedimentos no instante pedido usam recursos e lotes realmente protegidos.
Uma mensagem antiga também era conservada após editar a hora: corrigida.
2005 backend e 154 frontend passaram; percurso real genérico inconclusivo,
edição, candidato válido e aplicação passaram a 390/1440 px. O ensaio único
do movimento no ISOP passou em 30,86 s. Após integrar, 158 regressões backend
e 15 frontend passaram; seis páginas públicas passaram a 390/1440 px, plano
89 intacto. Ainda não conclui toda a auditoria.

### Provas Pendentes Do Objetivo Integral

Bloco publicado (02/10, secção 27): o gerador de transferências descartava
a terceira alternativa antes da validação comum e ocultava truncagem do beam.
Passa a emitir os estados já construídos e a propagar limites, sem aumentar
o orçamento ou mudar a ordenação industrial. Sete regressões novas e 88 focadas
passaram. O frontend isolado aplicou um candidato exato a 390/1440 px, mantendo
o lote protegido. Este ensaio genérico não resolve nem reconstrói setembro.
A pesquisa real identificou propostas sem montagem conservada e o âmbito
truncado da comparação BFP079; fecho dessas dependências e justificação das
transferências reais continuam pendentes.
Regressão integral: 2194 backend passaram, um ignorado; 188 frontend, lint,
TypeScript/build e Ruff passaram. Reinício da fixture, seis páginas a
390/1440 px e arranque com uma cópia recente da produção passaram, preservando
o snapshot. A publicação deste bloco não conclui os casos históricos.
Publicado no mesmo link com backup consistente, quatro ficheiros integrados,
88 regressões após integração e seis páginas públicas a 390/1440 px passaram.
Revisão 89 e plano ativo intactos; não se reconstruíram horários passados.

Bloco publicado e verificado (02/10, secção 22): a cache de transferências ignorava
operadores/equipas de setup libertados noutra máquina. Dezasseis de dezassete
regressões falharam no módulo antigo; as dezassete passaram após vincular a cache
ao estado completo e exato, sem mudar preferências. As 112 regressões focadas e 183
frontend passaram. Registados vinte ensaios na cópia do ISOP, todos seguros mas
parciais; 2130 backend completos passaram, um ignorado. O frontend aplicou o
candidato exato após remover ausências; reinício e seis páginas privadas a
390/1440 px passaram na primeira correção; dois testes adicionais revelaram
omissões de precisão/campanha, também corrigidas. Regressão integral final:
2132 aprovações e um ignorado; aplicação, reinício e navegador repetidos
nessa versão passaram. O teste opt-in de latência HTTP durante 151 s de cálculo simulado
passou. Publicado no mesmo link com backup consistente e 112 regressões após
integração; seis páginas públicas passaram a 390/1440 px, sem falhas de rede
registadas. Revisão 89, plano, configuração e decisões conservados exatamente.
O ensaio identificou perda possível do resumo de melhoria na reconstrução do
gate de replaneamento; permanece por corrigir/verificar entre os percursos.

Bloco seguinte publicado e verificado (secção 23): relatório completo e
resumo conservados no replaneamento, simulador, movimento manual, aplicação,
reversão e snapshots. Dez de onze regressões iniciais falharam antes;
14 novas regressões e uma regressão manual reforçada passaram depois.
2146 backend completos e 183 frontend passaram. O navegador verificou os
resultados `completed` e `partial/budget`, aplicação exata e dois reinícios;
seis páginas privadas passaram a 390/1440 px. Publicado no mesmo link com
backup consistente; 221 regressões após integração e seis páginas públicas
a 390/1440 px passaram. Plano, configuração, decisões e revisão 89 intactos.

Novo bloco publicado (02/10, secções 15–17): corrigida a geração de horários
que confundia libertação de operadores com início do setup. 23 casos permanentes
incluem enumeração finita de encaixes, recursos bloqueados e idempotência.
O navegador privado aplicou a preparação antes da libertação dos operadores,
com início produtivo imediato às 08:30; identidade/quantidade/setups conservados.
Dez compactações na cópia do ISOP passaram, sem substituir o plano público.
O ensaio revelou também alteração indevida de dados aninhados ao desserializar
configuração; leitura agora independente, com quatro regressões de gravação e
reabertura. A regressão integral revelou ainda um caminho de timeout que
recorria à alocação truncada no horizonte inicial (secção 17), também
reproduzido no código público. A construção completa existente passa a cobrir
esse caso sem confundir timeout com impossibilidade; três testes controlados
falharam antes e 158 regressões focadas passaram depois. Suíte completa final:
2035 passados e um ignorado, em 427,43 s. Os 154 testes frontend, lint,
TypeScript, build e Ruff passaram; navegação privada após reinício passou
a 390/1440 px. Publicado no mesmo link com backup consistente, dez ficheiros
integrados e 180 regressões backend após integração. As seis páginas públicas
passaram a 390/1440 px depois de confirmar o arranque; a primeira consulta
durante o reinício teve 502 e ficou registada. Plano ativo 89, configuração,
indicadores e decisões intactos. As explicações `left_shift_blockers` foram
recalculadas em 108 segmentos; todos os seus restantes campos ficaram iguais.
Não se reconstruíram os horários históricos.

Um bloco publicado não equivale ao cumprimento de todo o plano. Permanecem
explicitamente por auditar ou demonstrar no estado atual:

- As fixtures versionadas dos quatro casos de §8.1 têm percursos reduzidos
  no frontend (secções 33/34); faltam as provas integrais do ISOP histórico.
  Reconstruir setembro em produção exige esclarecer se os horários representam
  simulação ou execução efetiva. Não retirar a âncora BFP083 nem descongelar
  histórico para facilitar um teste.
- Enumerar movimentos em instâncias pequenas e confirmar o fecho no âmbito
  suportado (§8.2), sem transformar uma busca parcial em prova de ótimo.
- A fronteira pública do movimento distingue pesquisa inconclusiva de
  impedimento comprovado (secção 14); falta enumerar o fecho da pesquisa
  progressiva e conferir a mesma distinção nos restantes percursos.
- Relatório completo conservado entre cálculo, snapshots e aplicação (secção
  23). Falta concluir a auditoria integral de identidade/configuração/modelo
  e invalidação de candidatos entre todos os percursos de §6.5 e §7.
- Reconciliar a matriz de testes de concorrência, cancelamento, persistência,
  reinício, Consulta e respostas atrasadas de §8.4 com os contratos atuais;
  testes antigos verdes, sem inspeção do âmbito, não concluem essa prova.
- A causa da abertura pública vazia observada na secção 11 não foi demonstrada.
- Conferir a precisão de setups fracionários: o oráculo exploratório encontrou
  uma divergência de arredondamento no intervalo de operadores. A secção 18
  reproduz 27 falhas e corrige as fronteiras físicas e pesquisas de recursos
  numa cópia isolada; 33 regressões permanentes e o percurso real no navegador
  passaram. A regressão integral passou (2067 backend, dois ignorados), e o
  teste real ignorado passou depois sobre cópia da base. Frontend: 154 testes,
  lint, TypeScript/build; reinício e seis páginas a 390/1440 px passaram.
  Publicado com backup e integração delimitada; 274 regressões backend após
  integração passaram. A navegação pública teve duas tentativas com falhas
  de rede (o rastreio registou `ERR_NETWORK_CHANGED`); repetição sem comandos
  concorrentes passou as seis páginas a 390/1440 px. Revisão 89 e estado físico
  ativo conservados. Não conclui os restantes casos históricos ou a auditoria
  integral.
- Recuperação de consultas após falhas transitórias (secção 19): reproduzida
  página Risco que prometia restabelecer ligação mas não repetia o pedido.
  Na cópia isolada, `GET` tem duas repetições limitadas pelo mesmo deadline;
  escritas, erros de revisão e validação nunca são repetidos. Doze de 29
  regressões falharam antes; todas passaram depois, mais 183 testes frontend,
  lint, TypeScript/build e 94 regressões backend dos contratos envolvidos.
  Dez percursos no navegador a 390/1440 px passaram, incluindo falha
  persistente e desmontagem, sem escritas ou alteração do plano.
  Publicado com backup e preservação integral da revisão 89; os 183 testes
  frontend passaram também após integração. Navegação pública das seis
  páginas e recuperação delimitada do Risco passaram. O ensaio público
  completo de recuperação não passou: registou falhas de rede também nos
  módulos anteriores ao cliente. A estabilidade do transporte e a causa da
  abertura vazia antiga continuam não demonstradas; os horários de setembro
  não foram reconstruídos.
- Ordenação da mesma referência (secção 20): oito reproduções canónicas
  demonstraram troca de atrasos entre lotes com totais e OTD inalterados.
  A rotina passa pelo contrato comum por compromisso e respeita checkpoints.
  Doze regressões permanentes, 95 focadas finais, 2075 backend completos
  (mais quatro testes suplementares após essa corrida) e 183 frontend passaram;
  Ruff, lint, TypeScript/build e seis páginas privadas a 390/1440 px passaram.
  Publicado no mesmo link, com backup consistente e 95 regressões após
  integração. Plano ativo intacto. Seis páginas públicas a 390/1440 px
  carregaram, mas duas consultas stock tiveram falhas de rede registadas.
  Não comprova os horários históricos dos casos nomeados nem encerra a
  auditoria integral.
- Rotação de campanha e contexto de proteção (secção 21): reproduzida na
  cópia real a rotação de BFP082 que deixava a continuação atrás de BFP080,
  exigindo uma reinstalação não modelada. A proposta agora transporta a
  campanha conservando afinação e usa o alocador comum; setups não atravessam
  artificialmente o fecho. Provas históricas, âncoras e proteção explícita
  passam a definir o contexto das reparações; não se infere execução pela
  data de um candidato novo. O corte do plano ativo permanece igual.
  27 reproduções falharam antes; 95 regressões focadas e 73 de controlo
  passaram depois. Dez normalizações retrospectivas da cópia passaram
  física/conservação/contrato, com p50 5,097 s e p95 5,740 s apenas dessa fase.
  BFP082 urgente passou para D0 09:15; setups não aumentaram e a âncora ficou
  intacta. Frontend real isolado a 390/1440 px e 183 testes frontend passaram.
  A regressão integral final passou: 2115 testes e um ignorado, incluindo
  a base real copiada. Publicado no mesmo link após backup consistente;
  144 regressões passaram também na árvore publicada. As seis páginas
  públicas abriram a 390/1440 px sem erros de rede/HTTP/JavaScript ou escritas.
  Toda a árvore e o estado ativo foram conferidos; revisão 89, horários,
  quantidades, configuração e indicadores ficaram intactos. Os prints de
  BFP082 em D0 são do ensaio isolado, não do plano público. Não conclui os
  restantes casos, o fecho integral da pesquisa ou a estabilidade permanente
  da ligação.

## Registo

### Iteração 1 (29/09/2026)

- Criado worktree isolado (ver acima).
- Baseline (antes de qualquer alteração): `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`
  → **1874 passed, 1 skipped, 0 failed** em 462,75 s. Sem falhas preexistentes.
- Novo `backend/scheduler/improvement.py` (contrato v1):
  - `order_service` — reutiliza `compute_order_readiness`; identidade estável
    `(sku, cliente, dia, qtd, NP, ocorrência)`, duplicados separados; SKUs sem
    detalhe de cliente usam `op.d` (marcos canónicos).
  - `subcontract_lateness` — marcos de expedição para subcontratação por
    `(lote, op)`, verificados à parte.
  - `physical_setups` — fragmentos do mesmo setup contam uma vez; reinstalação
    noutra máquina conta; minutos com a precisão de `scoring` (0,1 min).
  - `physical_signature` — tempos, recursos, quantidades e outputs, sem warnings.
  - `no_loss_verdict`, `improvement_key` (ordem fixa §4.5), `lot_changes`.
- `tests/test_improvement_contract.py`: 13 testes, verdes.
  `ruff check` limpo nos dois ficheiros.
- Limitação conhecida: o marco de subcontratação compara dias de calendário
  (não dias úteis); suficiente para "não pode piorar", revisitar se o relatório
  precisar de dias úteis.

### Iteração 2 (29/09/2026)

- `backend/scheduler/campaign_tail.py`:
  - removida `_bounded_campaign_delivery_tradeoff` (aceitava +1 dia de atraso
    agregado quando o plano já estava incompleto);
  - movimento com custo de entrega (ranking agregado **ou** qualquer encomenda
    individual via `no_loss_verdict`) → `result.tradeoffs` (proposta
    `applied: False`), nunca aplicado; aviso "sugestão não aplicada";
  - adiamento puro para o último turno exige benefício estrito (entrega melhor,
    menos setups, menos minutos de setup ou menor `production_time_cost`).
    Sem isso não é movimento — senão deixava uma lacuna accionável que bloqueia
    a aprovação (`left_shift_opportunities`).
- `backend/scheduler/operational_audit.py`: removida
  `_is_campaign_tail_policy_gap`; `actionable_gap_opportunities` devolve todas
  as lacunas.
- `tests/test_campaign_tail.py` (§8.5): testes que esperavam a contrapartida
  antiga passam a verificar proposta não aplicada / ausência de reserva do
  último turno. 12 passed.
- Nota: o benchmark ISOP 17/03 (`tests/test_cpo.py`) já não carrega o ficheiro
  com a config actual (erro de gémeas BFP172) — o teste afirma esse erro e
  sai. Os números "validados" do CLAUDE.md não são reproduzíveis hoje.
- Impacto real: script `compare_replan.py` (scratchpad) replaneia o snapshot
  activo (cópia `data/plans.db`, só leitura) com o código original e o novo.
- Suíte completa após a iteração 2:
  `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider --deselect tests/test_campaign_tail.py`
  → 1875 passed, 1 skipped, 12 deselected (440 s); `tests/test_campaign_tail.py` → 12 passed.
- Replaneamento real: o percurso correcto (confirmado no código) é
  `POST /api/data/recalculate` → `_compute_schedule` com `config/factory.yaml`,
  sync de gémeas, `apply_calendars`, `reapply_calendar_mutations`,
  `optimize_preserving_started_lots(mode="normal", audit=True)`. O script do
  scratchpad reproduz esse percurso sem escrever na BD. As primeiras tentativas
  (config do snapshot + `apply_effective_planning_config`) falhavam também no
  código original — era erro do script, não do motor.

### Iteração 3 (29/09/2026) — bloqueio, loop parado para decisão do Luís

Scripts: `docs/tools/melhoria/compare_replan.py` (reproduz `POST /api/data/recalculate`
sem escrever na BD) e `docs/tools/melhoria/diag_recalc.py` (captura violações).

Comando (a partir do worktree; `CODE_ROOT` escolhe o código):
`CODE_ROOT=<árvore> PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/tools/melhoria/compare_replan.py data/plans.db out.pkl`

Resultado — **idêntico no código original (árvore servida) e no novo**:
- Congelamento no dia real (12): `NoValidCandidateError` — nenhum candidato
  completo fisicamente válido.
- Sem congelamento (dia 0): `schedule_all` falha a validação final com 8
  conflitos, iguais em todas as tentativas:
  - 6× `missing_tool_change_setup` (troca de ferramenta com 0 min de setup):
    PRM043 dias 26/40/62 (HAN002, BFP186, JTE003), PRM039 dia 32 (VUL180 após
    VUL181), PRM031 dia 15 (BFP171 após BFP184);
  - 2× `operator_capacity` Grandes turno B dias 47 e 54 (6 para 5).
  - Antes: ~17× "Crew overlap unfixable" e "Crew serialization skipped: both
    strategies cause tardy".
- Aviso de dados: "Twin BFP101: found 1135760X070 but missing 1955341X030 in current ISOP".

Conclusão: não é regressão deste trabalho; é um defeito preexistente na
construção/serialização de setups com os dados actuais. Sem candidato válido
não há baseline real para validar a melhoria automática (§10.1).

### Iteração 4 (29/09/2026) — decisão do Luís: corrigir o recálculo primeiro

Duas causas independentes, ambas preexistentes:

1. **Âncora manual ignorada fora do CP-SAT.** O plano activo tem a âncora
   `LOT_TWIN_BFP083_15 @ PRM031 2026-09-29T15:30` (motivo "teste", autor
   "utilizador"). Só `global_jit._apply_plan_anchors` a impõe; quando o CP-SAT
   não resolve no limite (1 s em `factory.yaml`), o fallback guloso e o
   pós-processamento colocam o lote na PRM039 às 07:00 → todos os candidatos
   falham `plan_anchor_violations` → `NoValidCandidateError`.
   **Correcção** (`backend/plans/frozen.py`): `_protected_lots` junta aos lotes
   iniciados os lotes ancorados cuja posição no plano base já cumpre a âncora;
   são reservados como histórico, a âncora sai temporariamente do problema
   residual (reposta pelo snapshot) e o lote é colado de volta intacto.
   Usado em `optimize_preserving_started_lots` e
   `compact_preserving_started_lots`. Aviso próprio "Posições manuais preservadas".
   Âncoras que o plano base não cumpre continuam entregues ao solver.
2. **`_repair_hard_constraints` reordenava máquinas.** Empurrava segmentos um a
   um e a regra de sobreposição ordenava pela hora actual; um segmento empurrado
   (dia bloqueado, ferramenta, equipa de setup) passava à frente dos sucessores
   → trocas de ferramenta com 0 min de setup (as 6 violações vistas).
   **Correcção** (`backend/scheduler/scheduler.py`): a regra de máquina usa a
   ordem original de cada máquina (rank fixado no início) e empurra a cauda
   inteira numa só varredura (sem isso: 41 s e timeout).

Testes: `tests/test_recalculation_regressions.py` (4). O teste da reparação
foi confirmado a **falhar no código original** e passar no novo.

Resultado real (`docs/tools/melhoria/compare_replan.py`, dia de congelamento real 12):
- Antes: `NoValidCandidateError`.
- Depois: candidato válido em 47 s, 0 violações, `best_effort` /
  `approval_required`; OTD 96,5 %, OTD-D 99,1 %, 7 atrasadas, atraso total 37,
  197 setups / 9195 min, `left_shift_opportunities` 3 — **igual ao plano activo**
  (o recálculo não encontrou melhor, mas já não falha).
- Recálculo desde o dia 0 (caso de ISOP novo): antes inválido (8 conflitos);
  depois válido em 47 s, 0 violações.
- Nota: a âncora "teste" no plano activo parece ser um resto de teste. Não foi
  removida — é uma decisão do Luís.
- Suíte completa após as correcções: **1889 passed, 2 errors** em `test_cpo.py`
  (quick mode, fixture realista) — regressão minha: com a ordem fixa, uma
  produção ordenada antes do seu próprio setup fazia a regra de máquina e a
  regra de lote empurrarem-se mutuamente até ao dia 115 (ciclo).
  Correcção: desempate "setup primeiro" no rank e, quando a produção de um lote
  aparece antes do seu setup, a produção passa para depois do bloco de setup e
  as posições trocam no rank. `tests/test_cpo.py` → 81 passed.
  Novo teste `test_production_ranked_before_its_setup_follows_the_setup_block`.
- Verificação final da iteração 4: `pytest tests/` → **1892 passed, 1 skipped, 0 failed**
  (398 s). Recálculo real repetido: mesmo fingerprint `32957702…`, 0 violações, 46,8 s.

### Iteração 5 (29/09/2026) — baseline de desempenho (§9.3)

Comando (10×, mesma máquina, dados e config fixos, dia de congelamento real 12):
`CODE_ROOT=$PWD /usr/bin/time -f "RSS_KB %M WALL %e" .venv/bin/python docs/tools/melhoria/compare_replan.py data/plans.db /dev/null`

| métrica | valor |
|---|---|
| tempo de cálculo (`optimize_preserving_started_lots`) | min 48,25 s · p50 48,35 s · p95 48,8 s · max 48,8 s |
| wall total (inclui carregar snapshot) | 48,8–49,4 s |
| memória máxima (RSS) | 147–148 MiB |
| fingerprint | idêntico nas 10 (`32957702…`) → determinístico |
| violações | 0 em todas |

Leitura: o modo `normal` já gasta ~48 s dos 60 s de orçamento. O §9.1 pede
10 s para melhoria + 10 s para fecho → a melhoria terá de caber no tempo que a
construção não usa, ou a construção tem de libertar tempo. A medir quando o
coordenador existir.

### Iteração 6 (29/09/2026) — geradores sob o contrato sem perdas (§6.3)

Mapa dos geradores (agente de pesquisa): além do campaign_tail, três rotinas
podiam **acrescentar setups automaticamente**:
- `repair_priority_inversions` — aceitava +1 setup com ganho estrito de entrega;
- `repair_alternative_machine_delivery` — nunca verificava setups;
- `repair_shift_capacity_exchange` — acrescenta sempre a reinstalação da ferramenta anterior.
A única decisão por texto de warning é `cpo/optimizer.py:271`
(`startswith("Máquinas alternativas:")`) → a tratar no bloco 7.

Medição antes de mudar (`docs/tools/melhoria/measure_setup_tradeoffs.py`, recálculo
real + cenários `CASE=prm039` (OEE 0,44) e `CASE=bfp079` (indisponível 12–18/10)):
**nenhuma das três aplicou qualquer movimento** em nenhum cenário → tornar a
regra estrita não altera os planos reais medidos. (bfp079: 13 atrasadas vs 7 —
impacto obrigatório da indisponibilidade, não da melhoria.)

Alterações:
- `improvement.py`: `contract_verdict` e `tradeoff_proposal` (resumo limitado,
  `applied: False`).
- `shift_exchange.py`: só devolve candidatos admissíveis; os outros vão para o
  parâmetro opcional `tradeoffs`. Na prática passa a gerador de propostas.
- `priority_normalization._candidate_rejection`: verificação por encomenda
  (`delivery_blocked`); setup extra com ganho → estado `setup_tradeoff`
  (`additional_setup_for_delivery_gain`), sem ganho → `resource_blocked`.
  `classify_priority_order_anomalies` mantém a contrapartida encontrada em
  qualquer rotação. Uma anomalia só resolúvel com setup extra deixa de contar
  como "evitável" (`permutable`).
- `alternative_repair.py`: movimento simples e coordenado passam pelo contrato;
  rejeitados → `AlternativeRepairResult.tradeoffs` (máx. 20).
- Testes convertidos (§8.5): `test_shift_exchange.py` (2),
  `test_priority_normalization_setup_tradeoff.py` (1). Fixture corrigido em
  `test_alternative_repair.py::test_tool_outage_reflows…` (BFP079): a procura
  canónica estava toda no dia 0, incoerente com os prazos 3/4/6/7 dos lotes; com
  a procura alinhada, a reorganização outubro→novembro passa o contrato.
- Suíte após iteração 6: 1892 passed, 1 skipped, 0 failed (422 s).

### Iteração 7 (29/09/2026) — "já reparado" deixa de vir do texto dos warnings (§3.3)

- `ScheduleResult.improvement_report` (novo, opcional). `improvement.record_verified`
  / `is_verified` ligam um âmbito de pesquisa à assinatura física do estado
  verificado.
- `schedule_all` regista `alternative_machine` quando a pesquisa termina (com ou
  sem movimentos). `_normalize_operational_result` só salta a pesquisa se o plano
  actual tiver exactamente essa assinatura; senão volta a pesquisar e regista.
  Removido `startswith("Máquinas alternativas:")`. Resultados criados noutros
  pontos sem relatório → pesquisa de novo (comportamento conservador).
- Testes: 2 novos em `test_improvement_contract.py` (15 passed).
- Recálculo real 3×: mesmo fingerprint `32957702…`, 46,97–49,96 s (baseline
  p50 48,35 s), 4 chamadas à pesquisa alternativa (igual).
- Suíte: **1894 passed, 1 skipped, 0 failed** (414 s).

### Iteração 8 (29/09/2026) — coordenador único (§5) ligado ao recálculo

`backend/scheduler/improvement.py::improve_plan`:
- geradores = rotinas existentes, locais primeiro (`earliest_legal`,
  `priority_inversions`, `campaign_tail`, `alternative_machine`,
  `shift_exchange`); cada um só **propõe** um plano completo;
- avaliador único: `validate_plan` + conservação → contrato por encomenda e
  setups contra o candidato corrente **e** contra a referência da fase →
  ganho estrito na ordem fixa §4.5 (`improvement_key`);
- após aceitar, recomeça a pesquisa (propagação abrangente, §5.5); estados
  visitados (assinatura física) são saltados → sem oscilação;
- paragem: `no_admissible_improvement` (→ `completed`), `budget`,
  `search_limit` (→ `partial`), referência inválida (→ `not_evaluated`);
- relatório: versão, estado, motivo, âmbitos, candidatos, aceites por âmbito,
  duplicados, rejeições por motivo, contrapartidas (máx. 10), resumo
  referência/final, duração.
- Testes `tests/test_improvement_cycle.py` (8): antecipação incorporada +
  idempotência; perda individual rejeitada com melhoria noutra encomenda;
  setup extra rejeitado; plano inválido nunca vira corrente; tentativa
  rejeitada não altera o corrente; gerador oscilante termina; orçamento 0 →
  `partial`; referência inválida → `not_evaluated`.

Integração (`backend/plans/frozen.py`):
- `improve_preserving_protected_lots`: corre o ciclo só no plano residual com
  lotes iniciados/ancorados reservados; cola de volta e revalida nos dados
  originais; qualquer falha → mantém o candidato completo.
- `optimize_preserving_started_lots`: fase de melhoria depois do candidato
  completo, orçamento `min(10 s, tempo restante − 5 s)`; relatório em
  `result.improvement_report` (as verificações anteriores só se mantêm se nada
  foi aceite).
- Primeira tentativa no plano real: `earliest_legal` foi rejeitado pelo
  avaliador por mexer em lotes históricos (prova de preservação quebrada) →
  motivou o trabalho no residual. Depois: 0,5 s, `completed`, 0 candidatos
  novos.

Audit (`operational_audit.py`, §6.4): as 3 `left_shift_opportunities` do plano
real eram **todas de lotes protegidos** — `BFP112_8` e `JTE004_11` (histórico,
dias 4–7 < dia 12) e `BFP083_15` (âncora). Passam a `protected_left_shift_detail`
com `protection` = `historical_lot_locked` / `manual_anchor` / `preserved_lot`
e deixam de contar como accionáveis. Testes: 2 novos em `test_operational_audit.py`.
- Suíte após iteração 8: 3 falhas corrigidas — (1) plano residual vazio era
  pontuado com reservas: `improve_plan` termina com `nothing_to_improve`;
  (2) `test_manual_move…requested_alternative` esperava `operational_gate_passed
  False` pela lacuna antes da posição manual → agora `True` com
  `protected_left_shift_detail = manual_anchor` (aprovação continua exigida);
  (3) resultados falsos sem `improvement_report` → leitura com `getattr`.
  Final: **1904 passed, 1 skipped, 0 failed** (412 s). Recálculo real: 48,3 s,
  `left_shift_opportunities` 3 → 0, fingerprint inalterado.

### Iteração 9 (29/09/2026) — restauro exacto e invariantes (§6.6, §7.4)

- `backend/plans/restore.py`: removidas as correcções escondidas no restauro
  (junção de setups destacados, `normalize_earliest_legal_plan`,
  `repair_short_runs_after_merged_campaigns`). Snapshot incompatível (modelo
  anterior / gémeas alteradas) → `ValueError("…exige recalculo explicito…")`
  salvo `recalculate=True`; `recalculate=True` recalcula às claras qualquer
  snapshot (incl. com conflitos), com aviso. `recover_jit_blocked` (flag
  explícita do chamador) mantém-se.
- `backend/api/plans.py`: `POST …/restore` aceita `"recalculate": true`.
- Arranque e cenários já usavam `preserve_exact=True` (sem alterações).
- Testes convertidos (§8.5): `test_plans.py` — gémeas desactivadas e política
  antiga exigem recálculo explícito; snapshot com buraco é reposto tal como
  guardado; setup destacado é diagnosticado (recusa) e só corrigido com
  `recalculate=True`. `test_scenario_identity.py` — as rotinas de reparação
  deixaram de estar acessíveis ao restauro. 54 passed.
- `docs/algorithm-planning-invariants.md`: nova secção "Melhoria automática sem
  perdas"; operadores corrigido (é restrição física validada, não só aprovação);
  lacunas protegidas; `setup_tradeoff`.
- Pendente para o frontend (bloco 10): oferecer "Repor e recalcular" quando o
  restauro devolver 409 "exige recalculo explicito".

### Análise pedida pelo Luís (29/09/2026, fotografias BFP112 e BFP079)

Script: `docs/tools/melhoria/analyse_cases.py` (replaneia o snapshot activo como se
hoje fosse `FREEZE_DAY=3`, i.e. antes dos dias das fotografias).

- No plano activo os dois casos (dias 4–8) são histórico (hoje = dia 12): o
  recálculo não os pode mudar; aparecem em `protected_left_shift_detail`.
- Código original, replaneando desde o dia 3: `NoValidCandidateError` (âncora
  "teste" — defeito já corrigido nesta cópia).
- Código novo, desde o dia 3: plano válido, OTD 96,5 %, 7 atrasadas, 198 setups,
  `left_shift_opportunities` 0, **31 transferências de ferramenta**.
  - BFP112 lote 8 (prazo D8) vai para a PRM019 D5 17:29; a PRM039 D4 fica cheia
    com BFP079 → a lacuna da fotografia não existe neste plano, mas por o plano
    ser outro, não porque a regra tenha sido provada. Falta a fixture §8.1.
  - BFP079 continua a saltar de máquina (PRM039→PRM031 D6, →PRM039 D14, …) e há
    idas-e-voltas em 1 dia (BFP082 PRM019→PRM039 D6 →PRM019 D7).
  - **Não tratado:** nenhum gerador propõe desfazer uma transferência (manter a
    campanha na mesma máquina e deslocar as outras referências). O avaliador já
    as aceitaria se não houver perda (transferências estão na ordem §4.5), mas
    ninguém as propõe. → próximo bloco: gerador "consolidar transferências".
- Suíte iteração 10: 1 falha `test_cpo.py::TestConvergence::test_different_seeds_stay_valid`
  (por investigar; máquina com load ~8–10 de outros projectos durante a corrida).

## Plano aprovado "BFP112 e transferências" (29/09/2026)

Plano: `/home/luis/.claude/plans/ok-analisa-isso-e-wiggly-prism.md`. Decisões do
Luís: OEE da PRM031 não se altera (a confirmar na fábrica); reprodutibilidade do
solver adiada; testes sintéticos + verificação local com a base real.

### Passo 1 — baseline (22:21–22:27, load 2,4–5,6)

| cenário | corridas | resultado |
|---|---|---|
| plano activo (dia real 12) | 3 | 47,8 / 49,1 / 50,8 s; fingerprint `32957702…` nas 3; OTD 96,5, 7 atrasadas, 197 setups, 0 violações |
| "hoje = dia 3" (`analyse_cases.py`) | 3 | idênticas: OTD 96,5, OTD-D 99,1, 7 atrasadas, atraso 37, 198 setups / 9270 min, **31 transferências**, melhoria 0 candidatos |

### Passo 2 — BFP112 (espera pela equipa de setup)

- Causa confirmada: `gap_filling._candidate_boundaries` gerava horas candidatas a
  partir dos segmentos do plano, mas **não** das reservas da equipa de setup de
  trabalho protegido (`data.setup_crew_reservations`, instaladas por
  `_install_frozen_reservations`). A hora em que a equipa fica livre (11:50)
  nunca era experimentada → o lote ia para o dia seguinte 07:00.
- Correcção: início e fim de `reserved_setup_segments(data)` do mesmo dia e grupo
  entram como candidatos. `scheduler._setup_capacity_ok_for_trial` e
  `_setup_aware_candidate_starts` ganham `data=` opcional e contam as reservas
  (passado em `_compact_segments`, `_left_shift_lots_into_empty_workdays`,
  `_try_pull_lot_to_previous_gap`; as restantes reparações de setup são cobertas
  pela validação final).
- `tests/test_setup_crew_wait.py` (3): reserva histórica (**falhava antes**:
  ficava no dia 2 07:00), bloqueador como segmento do plano (já passava),
  variante com outros ids e espera de 45 min. O motivo no Gantt passa a ser o
  verdadeiro (`blocked_by_setup_crew` explica as 11:50, não um dia inteiro).

### Passo 3 — protecção no juiz de melhoria

- `improvement._physically_valid` recebe a protecção da referência: lotes em
  `preserved_lot_proofs` têm de manter exactamente as mesmas linhas físicas
  (`preserved_lot_moved`); não pode surgir violação de âncora que a referência
  não tinha (`plan_anchor`). Relativo à referência → lotes fora do problema
  (resíduo) não geram falsos alarmes.
- Testes novos em `test_improvement_cycle.py` (3): mover lote preservado →
  rejeitado; quebrar âncora → rejeitado (ambos **falhavam antes**); outro lote
  ao lado de um ancorado continua a melhorar. 26 passed.

### Passo 4 — juiz com várias propostas por rotina

- `Proposal.subject`, `SkippedProposal`; uma rotina pode devolver um iterável
  (máx. `MAX_PROPOSALS_PER_CALL = 12` por chamada); `max_evaluations`
  (→ `evaluation_limit`); registo `proposal_log` por hipótese (resultado, motivo,
  detalhes, assinatura do estado em que foi julgada); `final_signature`;
  `tool_transfers` nos resumos; contagens por rotina.
- Avaliação única numa função `consider`; cópias por objecto em vez de
  `deepcopy` do plano; prazo filho (`planning_scope`) para interromper rotinas
  longas dentro do orçamento.
- **Compactação obrigatória:** depois de cada movimento aceite de outra rotina
  corre logo a compactação (`earliest_legal`). Se o orçamento acabar antes, é
  devolvido o último candidato compactado (`rolled_back_moves`).
- A procura continua pela rotina que acabou de ter sucesso e depois percorre as
  outras; só termina quando todas falham no plano corrente.

### Passo 5 — rotina "manter a ferramenta na mesma máquina"

- `backend/scheduler/transfer_consolidation.py`: `enumerate_transfer_hops`
  (blocos consecutivos por máquina; ida-e-volta primeiro, depois mesma velocidade,
  depois mais curtos), `consolidation_proposals` (preguiçoso): bloco forçado na
  máquina onde a ferramenta já está, trabalhos deslocados re-colocados (beam 4,
  opções: máquina que o bloco deixa / destino), limpeza de setups de ferramenta
  que continua montada, filtros baratos (menos transferências, setups ≤,
  nenhum lote do grupo passa a acabar depois do prazo → `would_delay`).
  Lotes iniciados/ancorados → `protected`. Grupo ≤ `MAX_COORDINATED_GROUP_SIZE = 6`
  (`group_truncated`). Cache por recursos (`execution_cache`).
- Ordem das rotinas: earliest_legal, priority_inversions, campaign_tail,
  shift_exchange, tool_transfers, alternative_machine (a mais cara no fim).
- Testes `tests/test_transfer_consolidation.py` (5): ida-e-volta consolidada
  (2→0 transferências, menos setups); também com as rotinas por omissão;
  idempotente e independente de nomes/ordem; lote protegido intocado (os
  outros juntam-se a ele); transferência justificada por máquina 2× mais lenta
  mantida, com motivo "atrasaria…". Nos primeiros cenários o motor encontrou
  melhorias legítimas que eu não previra (máquina rápida com folga) — os
  testes foram corrigidos para cenários realmente sem saída.
- Real (`analyse_cases.py`, dia 3): **31 → 19 transferências**, setups 198 → 197,
  OTD/atrasadas iguais, 0 lacunas, 57,6 s. Plano activo: setups 197 → 196,
  0 lacunas, 0 violações, 57,9–58,2 s (≈ +10 s, o orçamento de melhoria §9.1).
  Sem limite de tempo (medição à parte do resíduo): 30 → 11 transferências em 16 s —
  o orçamento de 10 s é o que limita.
- Nas simulações "dia 3", as transferências concretas das fotografias
  (BFP079_12, BFP082_8) envolvem lotes já iniciados antes do dia 3 → protegidas.

### Passo 6 — explicar as transferências que ficam

- `transfer_consolidation.explain_remaining_transfers`: para cada transferência
  do plano final, motivo e frase em português ("manter na PRM031 atrasaria: …
  (na PRM031 a produção demora 1,5× mais)", "envolve lote já iniciado…",
  "não avaliada neste cálculo (budget)"). Verdictos só reutilizados se dados
  sobre o estado final (`on_signature == final_signature`); senão
  `not_reevaluated` / `not_evaluated`. Máx. 20 itens.
- `improvement.improvement_gate_summary` → `gate_report["improvement"]`
  (informativo, não altera `apply_decision`) em `optimizer._apply_improvement_phase`
  (todos os ramos, incl. modo quick / sem tempo) e no fim de
  `frozen.optimize_preserving_started_lots` (plano já com histórico colado).
- Frontend: `GateReport.improvement` (`types.ts`); secção "Transferências de
  ferramenta mantidas (N)" em `GateReportCard.tsx` (junto a "Ver ações
  sugeridas", sem cartões novos); linha "Mudança de máquina" na janela do
  segmento em `GanttPage.tsx` (junto a "Porque não começou antes").
- Testes: 2 novos em `test_transfer_consolidation.py` (motivo actual com
  "2,0× mais"; verdicto de estado anterior nunca mostrado como actual);
  `frontend/tests/GanttPage.test.tsx` "explica porque um bloco ficou noutra
  máquina". Frontend: `npm test` 120 passed, `npm run lint` ok, `npm run build`
  ok, `tsc -b` ok (o `frontend/node_modules` do worktree passou a cópia local
  para as caches não escreverem na árvore servida).
- Isolamento de testes: `test_frozen_planning.py` e
  `test_same_reference_interruptions.py` substituem `scoring.compute_score`;
  módulos importados pela primeira vez durante esse patch ficavam com a versão
  falsa. Agora importam `transfer_consolidation` antes.

### Passo 7 — teste instável (provisório)

- `jit.py`: quando o construtor global não encontra candidato, o motivo
  `fallback_reason = "global_no_candidate"` segue em `result.feasibility`.
- `test_different_seeds_stay_valid`: exige sempre gates físico e de cobertura;
  aceita `no_candidate` só com esse motivo declarado. Novo teste que força o
  fallback e verifica o motivo. Correcção definitiva = reprodutibilidade
  (adiada por decisão do Luís).

### Verificação local com a base real

- `tests/test_real_plan_transfers.py`: abre `data/plans.db` só em leitura,
  salta se não existir; consolidação com 6 avaliações no plano activo → plano
  válido, transferências não aumentam, lotes preservados idênticos, cada
  transferência restante com explicação. Passou (não saltou) neste servidor.


## Publicação no sistema activo (30/09/2026 10:46, autorizada pelo Luís)

- Cópia de segurança: `~/backups/incompolinho/pre-melhoria-20260929-234418`
  (código `code.tar.gz` + `data/*.db` via backup SQLite + unidade systemd).
- Ensaio antes de publicar: backend novo na porta 18010 sobre cópias das bases
  actuais → arranque sem erros; 531 segmentos idênticos, revisão 83; única
  diferença `left_shift_opportunities` 3 → 0 (lotes protegidos).
- Publicação: `rsync` dos 48 ficheiros alterados/criados (sem `data/`, `.git`,
  `.venv`, `node_modules`) de `INCOMPOLINHO-melhoria` para `INCOMPOLINHO`;
  `systemctl --user restart incompolinho-backend.service` (de pé em 3 s).
  Frontend (Vite dev) actualizado por HMR; túnel Cloudflare intocado.
- Verificação só de leitura: 531 segmentos, hash `1fe1dc806a95` igual ao de antes,
  revisão 83, `left_shift_opportunities` 0, gates físico/cobertura ok; frontend
  serve "Mudança de máquina" e "Transferências de ferramenta mantidas"; link e API 200;
  sem erros no registo desde o reinício.
- Reverter: `cd /home/luis/projects/INCOMPOLINHO && tar -xzf ~/backups/incompolinho/pre-melhoria-20260929-234418/code.tar.gz && systemctl --user restart incompolinho-backend.service`
- Verificação final da suíte (pré-publicação): 1924 passed, 1 failed
  (`test_full_factory_no_tool_on_two_machines`, só sob load ~13 na corrida completa;
  passa isolado e com o ficheiro inteiro — fragilidade de tempo de relógio do
  solver, adiada). 10 recálculos cronometrados: 57,9–58,5 s (p50 58,35 s), 196 setups, 0 violações.
  Cenários: PRM039 OEE 0,44 → OTD 96,5, 7 atrasadas, 190 setups (antes 192), 0 violações;
  BFP079 indisponível 12–18/10 → OTD 93,6, 13 atrasadas (iguais), 196 setups (antes 197), 0 violações.

## Consistência Das Pré-Visualizações (02/10/2026)

Concluído na instância isolada o bloco de origem completa dos candidatos:
modelo/política/melhoria/robustez, regras, decisões manuais, overlays, plano e
todos os recursos. Cache separada do produtor e verificada antes de aplicar;
origens antigas incompletas não são aplicáveis. O modal recupera conflitos
preservando o pedido, sem repetir escritas ou descartar recusas de aprovação.

Backend completo: 2165 passaram, um opt-in ignorado; mais uma regressão de
aplicação exata e projeção de leitura passou depois dessa suíte. Vinte regressões
novas passaram juntas. Frontend: 185 testes, lint e TypeScript/build passaram.
Browser: duas sessões, duas aplicações e uma recusa 409; recuperação, reinício
e seis páginas a 390/1440 px passaram. Código e aplicações apenas em instância
privada; produção não foi usada para testar alterações do plano.

Detalhes e limitações na secção 24 de `causa-raiz-planeamento-2026-10-01.md`.
Não concluído: movimento sem alteração no lote inicial, matriz de casos reais,
fecho da pesquisa, lifecycle completo e desempenho global. A publicação deste
bloco será registada após guardas e verificação pública, sem substituir o plano.

Publicado no mesmo link após backup `20261002T045246Z-candidate-identity`.
Na árvore publicada, 297 regressões backend e 185 testes frontend passaram;
Ruff, lint, TypeScript/build e diff-check passaram. Seis páginas a 390/1440 px
verificadas em leitura. Plano e estado durável conservados na revisão 89;
serviços privados encerrados e serviços públicos ativos. Pendências mantêm-se.

## Lotes Existentes E Montagem Protegida (02/10/2026)

Validado isoladamente: movimento começa pela testemunha com posições fixas;
reorganização aloca os lotes existentes sem novo dimensionamento. Reparação de
campanha considera a posição reinserida; compactação usa a sequência física
completa e não altera o prefixo protegido. Remover setup redundante liberta
tempo produtivo real. Hora por omissão vem do primeiro fragmento produtivo;
horizonte de movimento e identidade do modelo são verificados.

Backend completo: 2176 passaram, 2 ignorados; frontend 188, Ruff, lint e
TypeScript/build passaram. Navegador privado a 390/1440 px verificou e aplicou
início atual, deslocação e reorganização com colisão; quatro lotes e quantidades
conservados, aplicação exata, sem erros. Reinício e seis páginas passaram.

Dez repetições na cópia real de um pedido sem alteração: p50/p95 25,736/27,040 s
antes e 2,899/2,978 s depois. Não equivalem em melhorias adicionais nem provam
ganho global ou ótimo; ambos reportam pesquisa parcial. Produção não alterada.
Detalhes, limites e artefactos na secção 25 de `causa-raiz-planeamento-2026-10-01.md`.

Publicação pendente das guardas finais. Casos iniciais BFP082, BFP112 e
transferências históricas BFP079 não ficam globalmente concluídos por este bloco.

Publicado após backup `20261002T055324Z-original-lot-allocation`: 243 regressões
backend e 188 testes frontend passaram também na árvore pública, com Ruff,
lint, TypeScript/build e diff-check. Seis páginas verificadas em leitura a
390/1440 px, sem erros. Guarda confirmou plano, configuração, regras e estado
durável intactos na revisão 89. Serviços privados encerrados; públicos ativos.
O bloco está publicado; a matriz histórica e a auditoria integral continuam abertas.

## Proteção Propagada No Fecho Canónico (02/10/2026)

Corrigida uma lacuna do bloco anterior: juntar setups e redividir movimentos
parciais podia alterar fragmentos protegidos, descartando uma antecipação válida
noutra máquina. Proteção explícita, histórica e manual acompanha agora todos
os passos; campanhas não deslocam membros fixos. Refluxos no início produtivo
são divididos pelos turnos antes de validar, sem perder trabalho ou quantidade.
A versão do contexto protegido invalida candidatos anteriores, sem migração
de snapshots ou alteração de objetivos industriais.

Backend final: 2186 passaram, 2 ignorados; frontend 188, Ruff, lint e
TypeScript/build passaram. Dez regressões novas. Browser privado a 390/1440 px:
remoção de indisponibilidade, candidato, aprovação, aplicação exata, reload e
reinício passaram; lote livre D2 -> D0, preparação protegida inalterada. Novo
backend sobre cópia recente da produção preservou os oito campos do frontend.

Dez ensaios retrospetivos reais conservaram quantidades, entregas e setups;
BFP082 inicial antecipou para D0 e VUL195/VUL174 para D8. Isto não substitui
o snapshot histórico protegido na produção. A comparação BFP079 na PRM031
terminou inconclusiva, sem prova de impossibilidade ou transferência necessária.
Detalhes e limitações na secção 26 da auditoria. Publicação pendente das guardas;
matriz histórica e auditoria integral continuam abertas.
Publicado após backup `20261002T065737Z-protected-normalization`.
Na árvore pública: 271 regressões backend e 188 frontend passaram; seis páginas
verificadas em leitura a 390/1440 px, sem erros. Estado de produção, regras e
identidade durável mantidos na revisão 89; serviços privados encerrados,
públicos ativos. Este bloco está publicado; matriz histórica, transferências
e auditoria integral continuam abertas.

## Montagem Retida Antes Da Alocação (02/10/2026)

Reproduzidas duas causas adicionais: o alocador preemptivo reservava preparação
antes de consultar a montagem física; ao separar lotes protegidos, geradores
de transferências e alternativas perdiam o predecessor que prova essa montagem.
O primeiro ensaio no frontend falhou mesmo após corrigir o alocador isolado.
O percurso passou depois de preservar o contexto físico completo na pesquisa,
com lotes protegidos fixos e projeção segura de volta ao problema residual.

28 regressões permanentes. Fixture privada a 390/1440 px: T permanece em M1,
produz 07:00-07:30 sem preparação adicional; U conclui no D1, 1010 peças e
entregas conservadas, setups 3 -> 2, lote ancorado intacto. Aplicação exatamente
igual ao candidato, reload e reinício passaram. Seis páginas sem erro.
Contexto protegido 3 invalida candidatos antigos, sem alterar plano histórico.

Revisão 89 validada fisicamente numa cópia. Os ensaios retrospetivos de
transferências mantêm cinco alternativas legais sem perda; não demonstram
novas melhorias nos casos históricos. O fecho de dependências e a comparação
BFP079 completa continuam abertos. Detalhes e limites na secção 28 da auditoria.
Regressão integral final: 2221 backend passaram, 2 ignorados; 188 frontend,
Ruff, lint e TypeScript/build passaram. Dez repetições reais por versão:
p50/p95 3,613/3,848 s antes e 3,597/3,698 s depois, com cinco propostas legais
sem perda em cada versão; não constituem prova de nova melhoria histórica.
Estado: validado isoladamente; publicação pendente das guardas finais.
Publicado após backup `20261002T083734Z-mounted-allocation`.
Na árvore pública: 255 regressões backend e 188 frontend passaram; seis páginas
em leitura a 390/1440 px sem erros JS/HTTP ou escrita inesperada. Guardas
confirmaram código integrado, configuração, regras e plano intactos na revisão
89, com 558 segmentos. Mesmo link e serviços públicos; ensaios privados encerrados.
Captura isolada: `/tmp/incompolinho-mounted-0700-detail.png`.
O bloco está publicado; fecho de dependências, BFP079 histórico e auditoria
integral continuam abertos. Não foi substituído o plano histórico em produção.

## Dependências Das Transferências (02/10/2026)

Reproduzidas alternativas perdidas porque um lote sem setup ficava fixo após
remover a sua montagem, ou após inserir outra campanha. O rebuild fecha agora
sucessores e componentes de montagem afetados, pelo predicado físico comum,
sem libertar produção protegida. Conserva máquinas compatíveis dos dependentes,
limite de seis, beam, deadline e cancelamento; limite atingido fica inconclusivo.

15 regressões novas e uma de identidade; nove falham no código anterior.
146 regressões focadas finais passaram. Frontend privado: T permaneceu na M1,
U1/U2 passaram para a M2; 645 peças, entregas e cabeça ancorada conservadas;
setups 3 -> 2, 90 -> 60 minutos. Aplicação exata, reload, reinício e seis
páginas em leitura a 390/1440 px passaram com a identidade final.

`TRANSFER_SEARCH_VERSION = 2` invalida candidatos antigos, não os snapshots.
A cópia recente da revisão 89 arrancou sem alterar os oito campos do frontend.
Enumeração real retrospetiva: nove propostas legais sem perda, contra cinco
antes. O snapshot histórico exato de 577 segmentos foi encontrado: quatro
alternativas válidas mantêm BFP079 na PRM031 desde 24/09 10:33, sem perda
por encomenda e com um setup a menos. Uma mantém as 22 transferências globais.
O código anterior a este bloco já constrói essas alternativas; não se atribui
esta descoberta ao novo fecho. A troca antiga permanece no histórico guardado,
que não é recalculado ao abrir a aplicação nem reescrito automaticamente.
Detalhes, evidências e limites na secção 29 da auditoria.
2237 backend passaram, 2 ignorados; 188 frontend, Ruff, lint e TypeScript/build
passaram. Dez ensaios por versão: p50/p95 3,579/3,639 s antes e 5,116/5,446 s
depois. Mais alternativas verificadas, mas pesquisa mais lenta, não ganho de
velocidade. Estado deste bloco: publicado e verificado.

Publicado após backup `20261002T102401Z-transfer-dependencies`.
Na árvore pública: 234 regressões backend, 188 frontend e Ruff passaram.
Seis páginas públicas a 390/1440 px passaram em leitura, sem erros ou escritas.
Código integrado; configuração, regras, snapshot e API intactos na revisão 89.
Mesmo link. Os cinco serviços privados desta execução foram encerrados.

Prints `/tmp/incompolinho-transfer-dependencies-archive-{gantt,detail}.png`
mostram a variante retrospetiva isolada BFP079/PRM031 em 24/09 às 10:33,
sem novo setup, com 197 setups, 9210 minutos e 22 transferências globais.
Foi aberta num backend privado, sem substituir o histórico público.
Este bloco está publicado; matriz histórica e auditoria integral continuam abertas.

## Controlos De Reposição (02/10/2026)

Reproduzido recálculo involuntário com `recalculate: "false"` e aceitação
de revisão pública nula. A rota e a função interna usam os validadores comuns
antes de descodificar ou calcular. Só booleanos reais controlam o recálculo;
revisão ausente/inválida é 400, obsoleta 409. O arranque interno mantém o
controlo opcional, sem ampliar acesso público nem mudar regras industriais.

83 regressões novas passaram; 66 falhavam antes. Suíte completa: 2330 backend
passaram, dois ignorados; 208 frontend, Ruff, lint e TypeScript/build passaram.
Frontend real a 390/1440 px: guardar, rejeitar entradas inválidas, repor e
repetir pelo recibo passaram, conservando horários/quantidades. Reinício da
fixture preservou os oito campos do snapshot. A cópia recente da revisão 89
passou em leitura sem alteração dos oito campos. Detalhes na secção 31.
Publicado e verificado após backup `20261002T113615Z-restore-contracts`.
Na árvore pública, 219 regressões backend e 208 frontend passaram. Seis
páginas públicas a 390/1440 px passaram sem erros ou escritas; guardas
confirmaram revisão 89, plano, configuração e regras intactos. Mesmo link.
Não conclui as provas históricas nem a auditoria integral.

## Contexto Protegido Na Prioridade (02/10/2026)

Três reparações viam apenas reservas do residual, perdendo a produção que
prova montagem e entregas protegidas. Agora reutilizam o contexto completo
e a projeção segura já usados por transferências e alternativas. Contexto 4
invalida candidatos antigos, sem modificar objetivos ou snapshots históricos.

15 testes novos: 11 falharam antes, quatro controlos já passavam porque a
compactação do pipeline completo compensava esta fixture. 137 regressões
focadas, 2345 backend completos (dois ignorados), 208 frontend, Ruff, lint
e TypeScript/build passaram. Frontend privado a 390/1440 px: remover ausência,
verificar, aprovar, aplicar, reload e reinício passaram. Produção urgente
no D0 às 08:00 sem novo setup; 60 peças, cabeça protegida e entregas conservadas.
Aplicação coincidiu exatamente com o candidato. Não é uma reconstrução do ISOP.

As seis páginas privadas da fixture e da cópia recente da revisão 89 passaram
em leitura. Detalhes e limites na secção 32 da auditoria. Dez ensaios por
versão passaram dentro do orçamento da melhoria;
p50/p95 7,560/7,670 s antes e 7,989/8,346 s depois, RSS 126,26/126,52 MiB.
É consistência adicional com custo ligeiramente superior, não ganho de
velocidade. Todos parciais por limite da pesquisa; não prova ótimo global.
Publicado após backup `20261002T121456Z-protected-priority`.
Na árvore pública, 137 regressões backend e 208 frontend passaram; Ruff e
`git diff --check` passaram. Seis páginas públicas a 390/1440 px sem erros
JS/HTTP ou escritas inesperadas. Guardas confirmaram código integrado, plano,
configuração, regras e identidade durável intactos na revisão 89. Mesmo link;
os quatro serviços privados foram encerrados. Matriz histórica e auditoria
integral continuam abertas; não foi substituído o plano ativo.

## Recálculo Confirmado E Ciclo De Operadores (02/10/2026)

Reproduzido o recálculo sem ligação ao candidato aprovado: o primeiro pedido
descartava o candidato no rollback e a confirmação executava o motor novamente.
O coordenador conserva agora o estado/resposta completos e aplica esse resultado
por identidade, sem nova otimização. Mesma proteção nas rotas antigas de
configuração e dados mestre. Aprovação sem candidato exige nova verificação;
conflito físico não é contornado. O frontend mantém candidato e operação para
confirmação e recuperação de resposta, sem retry automático ou novos cartões.
API antiga de operadores corrigida: metadados não são contagens, e valores
inteiros passam pelo validador partilhado.

Fixture versionada e relógio controlado. Frontend real privado a 390/1440:
ausências A/B -> 3/2 máquinas; retirar A -> 4/2; retirar B -> 4/4;
recalcular -> 4/4; 6000 peças mantidas. Candidato confirmado executado uma vez,
aplicação exata, aprovação durável, reload e reinício passaram. Medição por
varrimento independente dos intervalos. 26 regressões backend novas, duas
de capacidade com renomeação, quatro frontend; detalhes na secção 33 da auditoria.
Nova cópia da produção arrancou sem mudar os oito campos da vista da revisão 89.
Estado: validação integral e publicação pendentes. Isto não fecha a matriz
histórica, o orçamento completo, a enumeração do fecho ou toda a auditoria.

Regressão integral deste bloco: 2373 backend passaram, dois ignorados;
212 frontend passaram; Ruff, lint e TypeScript/build passaram. O aviso
existente de tamanho do bundle continua registado. Publicação pendente das guardas.


Publicado neste mesmo bloco após backup consistente
`20261002T133340Z-approval-identity`, com integração guardada dos 16 ficheiros.
Na árvore pública: 242 regressões backend e 212 frontend passaram;
Ruff, lint, TypeScript/build e `git diff --check` passaram. As seis páginas
públicas e privadas foram verificadas a 390/1440 px. Na produção, só leitura,
sem erros JS/HTTP ou escritas inesperadas. Guardas finais confirmaram código,
configuração, regras, snapshot e oito campos da vista intactos na revisão 89.
O endpoint de prova privado devolve 404 na aplicação pública. Mesmo link;
as três instâncias privadas foram encerradas. Isto conclui esta correção,
não a auditoria integral nem os casos históricos e medições ainda pendentes.

## Recálculo Limitado E Reproduções Nomeadas (02/10/2026)

Encontrada uma lacuna no orçamento do botão de recálculo: a melhoria tinha
limite de dez segundos, mas a robustez posterior não tinha deadline exterior.
`_compact_active_schedule` passa a delimitar cálculo, robustez, gates e
indicadores pelo mesmo orçamento de 60 segundos. A robustez reserva dez
segundos para o fecho; avaliação incompleta fica explicitamente não avaliada,
sem reutilizar percentagens antigas. Cancelamento continua a impedir aplicação.
Três regressões de deadline falhavam antes; os controlos de cancelamento e
rollback no fecho foram acrescentados. Sem alteração de objetivos ou UI.

Fixture `planning_opportunities_2026-09-17.json`: BFP112 antecipa de D5 para
D4 às 12:20 após recuperar operadores; BFP082 cobre a procura D0 às 07:30,
com continuidade; BFP079 deixa de transferir entre máquinas equivalentes.
24 testes cobrem ciclo, compactação, recálculo API e otimização completa,
com IDs originais e renomeados, física, quantidades, entregas e imutabilidade.
Frontend real privado a 390/1440 px: verificar, confirmar candidato, aplicar,
reload e reinício passaram nos três casos. O motor executa uma única vez;
segmentos brutos e lotes coincidem com candidato e snapshot durável.
São reproduções reduzidas, não uma reconstrução do ISOP ou prints da produção.

Dez repetições do percurso real de compactação numa cópia da revisão 89:
p50/p95 16,164/17,327 s antes e 15,437/16,214 s depois; RSS próprio
144,67/144,70 MiB. Candidato idêntico nas vinte execuções, contrato sem perda,
física e conservação passaram. A robustez estava sem deadline nas dez
execuções anteriores e ficou limitada nas dez novas. A diferença de tempo
não demonstra aceleração causada pelo patch. Dez ensaios da cópia real com
BFP079 bloqueada em 12-18/10 passaram: p50/p95 58,201/58,252 s,
RSS 160,17 MiB, mesma alocação, nenhuma produção no bloqueio e nenhuma
quantidade em falta. Robustez concluída em cinco e explicitamente não avaliada
nos outros cinco; todos sujeitos à confirmação existente. Isto não demonstra
ótimo ou elimina por si só os atrasos de outubro. Regressão integral e
publicação deste bloco ainda em validação.

Regressão integral: 2403 backend passaram, dois ignorados, em 467,13 s;
212 frontend, Ruff, lint e TypeScript/build passaram. Mantêm-se os avisos
existentes de TestClient e tamanho do bundle. Cópia recente da revisão 89
abriu sem alterar os oito campos da vista; as seis páginas privadas a
390/1440 px passaram só em leitura. Publicação aguarda backup e guardas.


Publicado após backup `20261002T144549Z-named-compaction-budget`.
Integração guardada dos nove ficheiros; 146 regressões backend e 212 frontend
passaram na árvore pública, mais Ruff, lint, TypeScript/build e diff-check.
Seis páginas públicas a 390/1440 px passaram sem erros ou escritas. Código,
plano, configuração, regras e identidade durável intactos na revisão 89.
Mesmo link; instâncias privadas encerradas; endpoint de prova privado 404.
Prints públicos não demonstram reparação retroativa: o histórico não foi
substituído. Correção de orçamento deste percurso publicada; auditoria
integral e restantes provas continuam abertas.

## Deadline Dos Escritores E Indicadores (02/10/2026)

Reproduzidas interrupções suprimidas pelos sete indicadores e gravação de
resultados depois do timeout/cancelamento no coordenador comum. A fronteira
de cálculo cobre agora callback, indicadores e validação até ao commit durável.
Os indicadores continuam a isolar erros ordinários, mas não interrupções do
planeamento; um indicador que devolve depois do limite não publica o valor.
Cancelamento/timeout antes do commit recupera YAML, regras, snapshot e memória.
Após commit durável, confirmação tardia devolve o recibo, sem falso insucesso.
Perfis quick/normal/smart mantêm 60 s; deep/max mantêm 300/600 s. Scopes
aninhados nunca ampliam o limite exterior. CPO, proteção histórica e movimento
manual usam a mesma reserva de dez segundos para concluir o percurso normal.

35 reproduções falharam antes: 24 no escritor/indicadores, seis na reserva
CPO/protegida, uma no fecho manual e quatro nos executores antigos.
58 testes novos incluem também controlos
de compatibilidade, perfis longos, rollback de ficheiros e resposta durável.
222 regressões focadas passaram. Os 212 testes frontend, Ruff, lint e
TypeScript/build passaram; regressão integral: 2455 backend passaram, dois
ignorados, em 482,86 s. Avisos existentes mantidos e registados na secção 35.

Frontend real privado: alterar OEE, verificar candidato, interromper aplicação
por timeout/cancelamento/preparação de ficheiros e repetir o mesmo candidato.
Os três insucessos preservam a revisão 1; confirmação tardia depois do commit
devolve sucesso, sem duplicação; reload conserva OEE e revisão 2. Verificado
a 390/1440 px, sem novos controlos nem alteração da produção. A cópia recente
da revisão 89 abriu com os oito campos intactos e passou seis páginas em
leitura nas duas larguras. Publicação ainda pendente; não fecha a matriz
histórica, a auditoria integral ou todos os benchmarks.

As rotas antigas mantêm agora o tipo de interrupção, em vez de o converter
em erro genérico 400. Dois testes HTTP confirmam os contratos 504/409 atuais,
sem publicação parcial. Os 58 testes novos e 211 regressões do conjunto final
passaram. Reinício real da fixture manteve snapshot, configuração e segmentos
iguais; aplicação coincidiu exatamente com o candidato. Regressão integral
final em repetição após esta última correção.

Dez ensaios da cópia real, BFP079 bloqueada em 12-18/10: p50/p95
50,815/50,849 s, RSS 159,36 MiB. Todos físicos e completos, origem intacta,
pesquisa parcial e robustez explicitamente não avaliada. Nove alocações
coincidiram; uma parou num candidato diferente, também válido, pelo orçamento.
Não demonstra determinismo sob corte por relógio nem ótimo. O ensaio mede
cálculo protegido, não duração total de aplicação HTTP/SQLite. A comparação
com a secção 34 não é uma medição causal de aceleração: a reserva reduziu
o tempo concedido à robustez, que antes terminou em cinco das dez execuções.

Regressão integral final: 2460 passaram, dois ignorados e uma falha em
`TestCPOSpecific.test_deterministic_seed`, em 565,19 s. Com seed 123,
duas execuções devolveram 58 e 54 setups. A causa dessa diferença ainda
requer investigação; não se elimina o teste nem se aumenta o orçamento para
ocultar o resultado. Artefacto `incompolinho-writer-budget-backend-final.xml`.
Publicação deste bloco continua pendente.

### Confirmação Da Janela De Cinco Dias

Verificação em leitura da aplicação pública: revisão 89, 558 segmentos,
`improvement.status=not_evaluated`, sem `improvement_report`. A janela de
material é de cinco dias úteis, não uma garantia de início no primeiro
instante possível. A normalização procura antecipações físicas e legais;
a comparação mantém entregas, setups e transferências antes do custo
temporal, e a pesquisa tem limites de tempo, propostas e iterações.
71 testes focados passaram na árvore publicada, artefacto
`incompolinho-five-workday-confirmation-20261002.xml`. Estes testes não
demonstram ótimo global nem antecipação de todos os lotes do plano ativo.
Não foi substituído ou recalculado o plano público nesta confirmação.

### Informação Do Solver E Polimento Repetível

A investigação da falha de seed identificou uma perda independente de
evidência: `_clear_robustness` apaga o gate antes da cópia de proveniência
em `_apply_improvement_phase`. Corrigida a ordem da captura; física e
decisão de aplicação continuam a ser reconstruídas para o candidato final.
O polimento CP-SAT usava quatro trabalhadores e a seed nativa por omissão,
sem receber a seed do pedido. Passa a um trabalhador e recebe a seed,
incluindo zero. Seis novas reproduções falharam antes e passam depois;
83 regressões focadas passaram. Não se atribui a falha anterior exclusivamente
ao paralelismo: resultados cortados pelo relógio podem continuar diferentes.

Frontend final repetido: `incompolinho-writer-ui-v4.json` e `-restart.json`,
aplicação exata, interrupção, repetição, reload e reinício passaram a
390/1440 px. Seis páginas da cópia recente do plano ativo passaram em
leitura (`incompolinho-writer-native-private-navigation.json`). Ruff,
212 testes frontend, lint e TypeScript/build passaram. A regressão integral
com o código final está em curso. Publicação ainda pendente.

Dez execuções nativas de uma sequência reduzida com seed 123 deram a mesma
ordem, com uma reorganização efetiva (`RUN_1`, `RUN_2`, `RUN_0`). Um ensaio
preliminar de prazos iguais devolveu ausência de alteração; não é usado
como prova de reorganização ou qualidade. A prova reduzida não garante
determinismo em pesquisas globais interrompidas pelo orçamento.

Regressão integral final: 2467 backend passaram, dois ignorados, em
540,12 s; o teste original de seed também passou, sem alteração do teste
ou aumento de orçamento. A falha anterior permanece registada; uma passagem
não prova repetibilidade universal com cortes temporais. Cópia recente do
plano ativo: 558 segmentos sem violações de física, quantidade ou âncoras.
Ensaio real único PRM039 OEE 0,44, histórico até D15 protegido: candidato
válido em 50,887 s, RSS 157,08 MiB, origem intacta e confirmação necessária.
Não se apresenta este único ensaio como média ou p95. Publicação em preparação.

Bloco 35 publicado no mesmo link, após backup consistente
`20261002T162624Z-writer-deadline`. Quinze ficheiros integrados com guardas;
171 regressões backend e 212 frontend passaram após integração, mais Ruff,
lint, TypeScript/build e diff-check. Seis páginas públicas a 390/1440 px
passaram sem erros ou escritas. Identidade, configuração, regras, indicadores,
558 segmentos e revisão 89 intactos; nenhum recálculo do plano ativo.
Endpoint privado de prova 404; servidores de teste encerrados.
Não conclui a auditoria integral, os casos históricos ou a prova de primeiro
início possível para cada lote. A distinção entre simulação e produção
realizada em setembro foi solicitada; a restante auditoria continua ativa.

## 36. Conservar A Melhoria Já Validada

Reproduzida perda de uma melhoria aceite quando uma pesquisa posterior
esgotava o tempo: `_optimize` devolvia a construção inicial e o coordenador
voltava a retê-la. Corrigido na cópia isolada com retenção canónica e cópia
independente, notificação do polimento CP-SAT e transporte do rasto do solver.
Cancelamento e prazo exterior não são convertidos em sucesso.

Corrigidas também divergências entre datas agregadas e entregas detalhadas.
Registos descritivos antigos continuam compatíveis, mas já não desligam a
validação da origem dos registos atuais. Preferências, regras e orçamento
inalterados. 40 testes novos; 211 regressões focadas passaram. A primeira
regressão completa encontrou duas incompatibilidades em fixtures antigas de
gémeas; corrigidas sem alterar os testes. Regressão integral final: 2507 passaram,
dois ignorados, em 478,28 s (`incompolinho-last-candidate-backend-final.xml`).

212 testes frontend, lint e TypeScript/build passaram. Aplicação exata,
interrupção, repetição, reload e reinício passaram no navegador privado a
390/1440 px. A cópia recente da revisão 89 passou física, conservação e
âncoras, mais seis páginas em leitura nas duas larguras. Publicação pendente.
As seis páginas da fixture passaram também em leitura nas duas larguras.
O plano ativo não foi recalculado e mantém `improvement.status=not_evaluated`;
esta correção não constitui prova de antecipação máxima de todos os lotes.

Conferência em cópia do snapshot 89, com história anterior a D15 protegida:
uma transferência BFP181 aceite, 14 para 13 transferências, custo temporal
reduzido, entregas e setups sem perdas. Duração 16,998 s, RSS 142,40 MiB;
`partial/search_limit` (`incompolinho-last-candidate-compact.json`).
O snapshot publicado tem zero violações JIT e máximo de cinco dias úteis
de antecipação, mas não tem prova de início mais cedo possível. O candidato
da cópia não foi aplicado à produção.

Dez ensaios BFP079 indisponível em 12-18/10 na cópia real: todos físicos,
completos, quantidades conservadas, bloqueio respeitado e origem intacta.
p50/p95 50,852/50,934 s; RSS 160,50 MiB. Nove alocações iguais, uma diferente
também válida; pesquisa parcial e robustez não avaliada. Não prova ótimo ou
determinismo com cortes por relógio, nem mede a duração total de aplicação HTTP.
Artefacto `incompolinho-last-candidate-bfp079.json`.

Bloco 36 publicado no mesmo link, após backup consistente
`20261002T173127Z-last-candidate`. Sete ficheiros integrados com guardas;
211 regressões backend e 212 frontend passaram após integração, mais Ruff,
lint, TypeScript/build e diff-check. Mantém-se o aviso de bundle de 533,40 kB.
Seis páginas públicas a 390/1440 px passaram sem erros nem escritas
(`incompolinho-last-candidate-public-navigation.json`). Código conciliado,
snapshot ativo, configuração, regras, indicadores e revisão 89 intactos.
Servidores privados encerrados; endpoint de prova privado 404.
Não recalculou os 558 segmentos ativos, não fecha a auditoria integral e
não demonstra primeiro início possível para todos os lotes.

## Bloco 37: montagem física e substituição autorizada

Prova de montagem corrigida na cópia: apenas preparação posterior à última
mudança física conta, independentemente do ID de campanha. Diagnósticos e
alocação partilham a prova. 21 regressões permanentes; bateria integral
2526 passaram e dois ignorados, mais os dois casos manuais adicionados depois
da recolha. 212 frontend, lint e TypeScript/build passaram.

Recálculo normal real isolado, 53,732 s: conserva a alocação e passa física,
quantidades, origem, histórico, âncoras e repetição do recibo; 390/1440 px verdes.
Auditoria: 202 lotes, 49 protegidos, 153 móveis; 236 combinações de 152 campanhas
em 2,080 s. Dois testemunhos de antecipação sem perdas: BFP181 (26/11 08:48
PRM043 em vez de 27/11 13:05 PRM019) e BFP186 (20/10 08:30 PRM039 em vez
de 14:55 PRM043). Compactação existente aceita BFP181 e reduz transferências
14 para 13. BFP186 continua fora do âmbito de reparação de entrega da etapa
de alternativas. Não há prova de antecipação máxima e não se muda a hierarquia
de objetivos para um caso isolado. Publicação e aplicação pendentes.

Publicado bloco 37 no mesmo link com backup `20261002T191127Z-mounting-evidence`.
256 regressões após integração. Aplicado candidato exato do recálculo
conservador: revisão 90, snapshot `046b5d08b9884672ba2f9cf7e0f024d7`,
BFP181 antecipada e transferências 14 para 13; histórico, quantidades,
setups, configurações e compromissos sem perdas. Recibo repetido e reinício
preservam exatamente o resultado. Seis páginas públicas 390/1440 px verdes.

Auditoria posterior à aplicação: 236 combinações, 235 sem início anterior,
um testemunho BFP186 permanece (20/10 08:30 PRM039 contra 14:55 PRM043).
Física, origem, gémeas e contrato verificados; não aplicado e não corrigido
por uma preferência especial. Causa: procura de alternativas limitada a risco
e melhoria de entrega, não aos desempates temporais de toda a procura pontual.
Zero violações JIT, máximo cinco dias úteis. Não fecha antecipação máxima
ou auditoria integral. Servidores privados encerrados.

## Bloco 38: cobertura das antecipações finitas

Pedido: pesquisar antecipações também para produções já dentro do prazo,
sem alterar preferências por referência. A árvore atual já continha as
vizinhanças de reinserção de uma, duas e três campanhas. Confirmado um segundo
corte: o coordenador descartava o resto do iterador após 12 propostas ou
64 hipóteses rejeitadas, mesmo numa enumeração finita e com tempo disponível.
Uma alternativa válida posterior ficava por verificar.

Corrigido `Generator.proposal_limit`: estas três enumerações usam o deadline
e o orçamento global de avaliações, sem o corte genérico por chamada. Os
geradores potencialmente ilimitados mantêm os limites anteriores. Mantidos
o avaliador físico/comercial, a hierarquia atual, cancelamento, conservação e
o diagnóstico de pesquisa parcial. Não implica pesquisa global exaustiva.
As reinserções reutilizam também `protected_lot_ids`, incluindo âncoras manuais
na seleção, além das provas de histórico; antes só as provas eram excluídas.

Regressões: sete reproduções iniciais falharam antes da correção. O conjunto
permanente inclui propostas duplicadas, fisicamente inválidas e com perda de
entrega antes de uma alternativa válida, as três vizinhanças, identificadores
renomeados, prazo, cancelamento, âncoras, material, indisponibilidades e remoção,
OEE por máquina. 222 regressões focadas passaram; 212 testes frontend, lint,
TypeScript/build passaram. Bateria integral final: 2584 passaram, dois ignorados,
516,64 s. As 38 novas regressões estão incluídas nessa bateria.

Cópia real: recálculo normal em 51,630 s, candidato BFP186 a 20/10 08:00
PRM043, não aplicado. Compactação final pela API aplicada apenas na cópia:
revisão 90 para 91, BFP186 a 20/10 08:30 PRM043 em vez de 14:55; setup
08:00-08:30. 553 segmentos; física, origem, quantidades, gémeas, entregas,
histórico e repetição do recibo verificados. Resultado `partial/budget`,
não prova de antecipação máxima. O contrato atual permite setups adicionais
sem perda de entregas; esta correção não muda esse contrato.

Seis páginas e prova Gantt reais a 390/1440 px passaram na instância isolada;
uma tentativa de captura assumiu erradamente que o SKU estava no texto do
bloco com pouco zoom. Corrigido apenas o seletor do teste, usando o título
real; sem alteração de interface. Artefactos `/tmp/incompolinho-coverage-*`.
Plano público permanece na revisão 90, snapshot `046b5d08b9884672ba2f9cf7e0f024d7`.
Não publicar alterações recentes de outras tarefas ao reiniciar a árvore viva.

Dez repetições de compactação do plano copiado: BFP186 antecipada em todas,
49 lotes protegidos intactos, física/conservação/contrato por encomenda verdes,
inputs intactos. p50 10,843 s e p95 por nearest-rank 10,928 s, incluindo fecho
da compactação; não inclui toda a API nem constitui SLA de produção. Pesquisa
ampla permanece `partial/budget`. Publicação e substituição pública não feitas;
apenas os ficheiros desta correção serão integrados na árvore de trabalho.

Integração concluída exclusivamente nos cinco ficheiros desta correção;
222 regressões passaram novamente na árvore de trabalho. Reinício da instância
isolada conserva a revisão 91 e a antecipação; prova frontend passou de novo.
Identidade/snapshot público intactos após integração. Serviços públicos não
reiniciados; não confundir código integrado com correção ativada no link.

## Bloco 39: orçamento adaptativo e reutilização incremental

Pedido: aproveitar melhor o tempo da pesquisa, sem alterar prioridades ou
regras por referência. O limite fixo de 10 segundos existia na melhoria do
otimizador, compactação com histórico e fecho dos movimentos manuais. Além
disso, as permutações repetiam alocações idênticas; mudar trabalho futuro
invalidava pesquisas já concluídas em dias anteriores. As validações também
recalculavam os fingerprints dos mesmos lotes históricos.

Correção isolada: orçamento comum igual ao tempo restante menos a reserva
de fecho (10 segundos no modo normal de 60). Só depois de existir candidato
completo, a pesquisa auxiliar e a robustez deixam tempo para as vizinhanças
comuns. A primeira construção não perde orçamento; scopes filhos nunca
prolongam o deadline do pedido. O modo rápido mantém o comportamento anterior.
A compactação direta estabelece também um scope exterior de 60 segundos.

Cache limitada à execução, até 512 alocações, com identidade dos dados,
configuração, modelo, campanha, máquina e fronteira de recálculo. A dependência
inclui trabalho de todas as máquinas: operadores, equipa de setup e ferramenta
são recursos partilhados. Uma alocação completa pode reutilizar o prefixo até
ao seu último dia; uma falha depende de todo o horizonte. Mudanças nesse
contexto invalidam a entrada, e cancelamento é verificado também nos hits.
Os resultados são cópias independentes. Provas de histórico só reutilizam o
digest após igualdade exata de todos os campos do lote e segmentos, com
até 256 entradas. Não são atalhos à validação física ou comercial final.

Regressões novas: 68 casos de orçamento, deadline, cancelamento, invalidação,
prefixos, isolamento entre execuções, memória limitada e provas de histórico;
mais uma comparação real de três rondas com e sem cache. Esta comparação
produziu exatamente o mesmo fingerprint, conservou os 49 lotes protegidos,
quantidades, âncoras e contrato por encomenda. A fixture privada da revisão 91
foi congelada em leitura; só o manifesto é versionável.

Dez compactações da cópia real, D15 protegido: p50 50,626 s, p95 50,669 s,
RSS máximo 129,33 MiB. Nove lotes antecipados em todas; 30 ou 31 movimentos
aceites, 53 ou 54 candidatos avaliados, entre 4425 e 4522 alocações reutilizadas
por execução e 238 entradas retidas. Física, origem, quantidades, gémeas,
histórico e entregas sem perdas em todas. Comparação inicial, antes desta
correção e na mesma árvore: 11,150 s, oito movimentos aceites. A duração total
maior é deliberada: mais pesquisa dentro do orçamento, não uma promessa de
latência inferior. Os contadores de reutilização não são um benchmark de
aceleração com trabalho fixo.

Resultado continua `partial/budget`. Houve dois fingerprints: o corte perto
do último movimento muda a ordenação de BFP100/BFP101, sem violar o contrato.
Isto não demonstra determinismo com corte por relógio, pesquisa esgotada,
ótimo global, nem antecipação máxima de todos os lotes. As nove antecipações
medidas não são necessariamente os mesmos nove casos da auditoria anterior:
a árvore já tinha alterações de vizinhanças de outra tarefa, preservadas.

Artefactos: `/tmp/incompolinho-adaptive-final-benchmark.json`,
`/tmp/incompolinho-adaptive-candidate.json`; candidato apenas em ficheiro,
não aplicado. Bateria integral: 2743 passaram, dois ignorados, 678,92 s;
Ruff passou nos ficheiros alterados. Único aviso: depreciação do TestClient
Starlette/httpx, independente desta correção. Integrados apenas os sete
ficheiros backend e os respetivos testes, benchmark e manifesto; nenhuma
alteração de interface. Após integração: 302 regressões passaram em 21,23 s,
incluindo movimentos, candidatos, deadline e compactação; Ruff e diff-check
passaram. Os ficheiros integrados são idênticos aos da cópia validada.
Plano público mantém revisão 90 e snapshot
`046b5d08b9884672ba2f9cf7e0f024d7`; não houve reinício ou publicação.
