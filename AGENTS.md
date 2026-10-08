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
  algorítmica; 30 pedidos (artefacto local não incluído)
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
   mais urgente ganhar pelo menos 1 h; abaixo disso, os minutos exatos
   desempatam. Cada melhoria é comparada com o plano atual e com o de partida
   (`policy.anticipation_compare`, `improvement.improvement_better`).
4. **Objetivos seguintes:** menos setups físicos/minutos, menos transferências,
   menor alteração do plano. Não podem fazer perder uma antecipação admissível.
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

Num ciclo gémeo confirmado, a regra industrial existente partilha material:
`R_ciclo = min(R_outputs)` e `U_ciclo = min(U_outputs)`. Conservar os marcos
individuais; não aplicar inadvertidamente `max(R_outputs)` de um modelo genérico.
Stock coproduzido não cria encomenda ou expedição fictícia.

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
- Preservar lotes protegidos integralmente e âncoras manuais. Um bloqueio por
  histórico/âncora não é um bloqueio de máquina, material ou operadores.
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

## 6. Solver e limites de compute

- Reutilizar OR-Tools CP-SAT e os alocadores existentes. Primeiro construir
  uma solução completa válida; depois melhorar de forma limitada e mensurável.
- Começar por inserção no primeiro intervalo viável e procura em todas as
  máquinas elegíveis; depois trocas locais e pequenos grupos acoplados por
  máquina, ferramenta ou equipa. CP-SAT local trata os casos restantes.
- Geradores propõem; um único avaliador aplica o mesmo contrato a planeamento,
  melhoria, movimento, explicação e persistência. Não duplicar prioridades.
- Começar com um worker do solver; medir antes de aumentar. O código atual já
  usa um worker. GA/ML não são o caminho operacional e não são necessários
  para corrigir a falha reproduzida.
- Confirmado em 05/10/2026 (substitui a nota de 03/10): compactação,
  movimento manual, CPO e recálculo dão ao ciclo de melhoria o tempo que resta
  no orçamento do pedido menos a reserva de fecho
  (`planning_control.improvement_time_budget`); na revisão 90 a compactação
  demora ~50 s. Mais pesquisa, não menor latência.
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
- Um deadline exterior abrange preparação, pesquisa, fecho, validação e escrita.
  Subfases nunca reiniciam o relógio. Preservar a reserva de fecho existente.
- Guardar o último candidato completo validado fora do solver. Timeout de uma
  fase não o apaga; cancelamento impede commit. Se não houver plano completo
  válido para os inputs atuais, devolver diagnóstico, não um snapshot obsoleto.
- `UNKNOWN`/limite de pesquisa não significam `INFEASIBLE`. Inviabilidade num
  subproblema com restantes lotes fixos não prova inviabilidade global.
- `completed` refere-se ao âmbito descrito. Não prometer ótimo global nem
  determinismo apenas por usar seed fixa e corte de tempo real.

## 7. Alterações e validação

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
`scheduler/policy.py`; avaliação e ciclo em `scheduler/improvement.py`;
vizinhanças N1–N3 e alocador "primeiro intervalo viável" em
`scheduler/alternative_repair.py`; N4 em `scheduler/local_cpsat.py`; proteção em
`plans/frozen.py`; orçamento em `planning_control.py` (todos sob `backend/`).
GA/MAP-Elites só offline em `cpo/offline_ga.py`.

Verificação: fixtures reais congeladas em `tests/fixtures/private/` (fora do
git; manifestos em `tests/fixtures/snapshots/`, criados por
`scripts/freeze_snapshot_fixture.py`); casos §8.1 em
`tests/test_acceptance_cases.py`; oráculo independente em `tests/oracle.py`;
benchmark repetível em `scripts/benchmark_solver.py`.
