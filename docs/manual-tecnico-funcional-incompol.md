# INCOMPOL

## Manual técnico e funcional do sistema de planeamento

**ProdPlan ONE / INCOMPOLINHO**  
INCOMPOL-MTF-001 · Edição 1.0 · 16 de setembro de 2026  
Edição compacta: máximo de 20 páginas, incluindo capa e índice.

## 1. Objetivo, âmbito e conceitos

O **ProdPlan ONE / INCOMPOL** transforma necessidades do ficheiro ISOP num plano com máquinas, ferramentas, equipas de setup e operadores. Calcula entregas, stock, carga e risco; permite comparar cenários, alterar regras e aplicar planos validados. Este manual destina-se a planeamento, produção, gestão e manutenção do software.

**Referência.** Descreve código de trabalho, configuração e interface consultados em 16-09-2026, incluindo alterações locais. Distingue regras pretendidas de comportamento implementado; não certifica uma versão imutável de produção. Os valores são uma fotografia da configuração, salvo invariantes identificadas.

| Conceito | Significado operacional |
| --- | --- |
| SKU / referência | Artigo acompanhado em necessidades, produção e stock |
| Operação | Necessidades agregadas da mesma referência, máquina e ferramenta |
| Lote | Quantidade dimensionada para satisfazer uma ou mais necessidades |
| Campanha | Trabalho que conserva uma identidade de afinação compatível |
| Segmento | Parcela de setup e/ou produção numa máquina, dia e turno |
| Família de setup | Referências sucessivas com afinação partilhada confirmada |
| Gémeas | Duas referências produzidas simultaneamente no mesmo ciclo |
| Snapshot / revisão | Versão persistida / contador do estado aplicado |

Uma referência pode ter vários lotes; um lote, vários segmentos. **Lotes, segmentos, referências e encomendas não são contagens equivalentes.** Em Entregas, uma encomenda é uma necessidade líquida por cliente, referência e data, não necessariamente uma ordem ERP identificada.

**Datas.** D0 é a primeira data importada; `day_idx` é a posição na sequência diária, que pode incluir fins de semana. Entrega ao cliente, prazo produtivo, envio externo e libertação de material são marcos diferentes. Índices negativos preservam compromissos anteriores a D0, mas não autorizam execução antes do horizonte.

**Limite do modelo.** O plano é uma previsão, não confirmação de execução. Não existe integração contínua nativa com MES, movimentos reais de armazém ou receções de matéria-prima. «Agora», «pronto» e «stock» são informação planeada. Fuso operacional: `Europe/Lisbon`.

## 2. ISOP, necessidades e carregamento

**Entrada.** Excel `.xlsx`, não vazio, até 25 MiB. O leitor usa a folha ativa; procura «Cliente» na coluna A nas primeiras vinte linhas e reconhece colunas normalizadas. As datas devem ser cabeçalhos Excel reais, diários, ordenados e contíguos. O parser não comprova integralmente a continuidade.

Lê cliente, referência, designação, máquina, ferramenta, cadência, pessoas, eco-lote, WIP, ATRASO e necessidades. Fórmulas usam resultados guardados no Excel: o servidor não as recalcula. WIP e ATRASO não criam automaticamente fornecimentos/lotes adicionais. Setups e alternativas efetivos provêm da configuração.

**Necessidade NP.** O último positivo anterior ao primeiro negativo é stock informativo. Cada negativo origina necessidade positiva. Exemplo: `100, 40, -60, 0, -80` produz stock 40 e necessidades `0, 0, 60, 0, 80`. NP já é necessidade líquida: **não se desconta nem se soma novamente o stock inicial** nos lotes/cobertura.

**Transformação.** Agrega clientes por referência/máquina/ferramenta, preservando detalhe comercial. Aplica OEE, alternativas, setups, calendário, subcontratação e correções. Rotas ambíguas são rejeitadas. A classificação final das gémeas usa `config.twins` atual.

**Fluxo normal.** «Trocar ISOP» inicia leitura, transformação, DQA, cálculo e gates em segundo plano. A interface envia a hipótese **todas as máquinas livres em D0** e aprovação automática das exceções permitidas, atribuída a «sistema». Limpa fornecimentos comprometidos; não transporta automaticamente WIP/plano anterior. Mantém feriados, manutenção e bloqueios persistentes. O upload atual não exige confirmação humana individual desse pressuposto.

**Estados.** Preparação → fila → execução → aplicado, bloqueado, falhado ou cancelado. A API também suporta preparação/confirmação/aprovação separadas; pode devolver `prepared`, `awaiting_approval` ou `stale` quando a origem muda. Bloqueios físicos, de cobertura, material e sequência não podem ser aprovados.

**Recuperação.** Fechar/atualizar a página não cancela cálculo confirmado. «Ver plano atual» oculta acompanhamento; «Acompanhar carregamento» reabre-o. Cancelar impede aplicação posterior conforme o estado. Se houve aplicação mas falha visual, atualizar dados repete consultas, não a importação. Consultar o mesmo identificador antes de repetir pedidos.

## 3. Calendário, capacidade e recursos

| Configuração atual | Valor / regra |
| --- | --- |
| Turno A | 07:00–15:30; 510 minutos |
| Turno B | 15:30–23:50; 500 minutos |
| Capacidade diária | 1 010 minutos; intervalos fora dos turnos não contam |
| Grandes | PRM019, PRM031, PRM039, PRM043 |
| Médias | PRM042 |
| Operadores Grandes / Médias | A: 6 / 9; B: 5 / 4 |
| Equipas de setup | Uma simultânea por grupo, independentes entre grupos |

**Calendário.** Fim de semana fechado por defeito; dias extra podem abrir datas específicas. Feriado explícito prevalece sobre abertura extra. Máquina inativa/dia fechado têm capacidade zero. Turnos suportados pertencem ao mesmo dia.

```text
Capacidade disponível = minutos abertos − indisponibilidade nesses minutos
Carga = minutos de produção + minutos de setup
Utilização (%) = carga / capacidade disponível × 100
```

Exemplo: produção 700 + setup 60 em 1 010 disponíveis dão **75,2%**. Com manutenção de 200 minutos dentro do horário, ficam 810 e a utilização é **93,8%**. Não se multiplica capacidade por OEE novamente: já influencia a duração produtiva. Capacidade zero é fechada/indisponível.

**Bloqueios.** Máquina, ferramenta e operadores podem ter indisponibilidades com datas, categoria e motivo: avaria, manutenção, ensaio ou ausência. Conta a interseção com o horário aberto; sobreposições não duplicam minutos. Bloqueio de ferramenta acompanha-a para máquinas alternativas.

**Elegibilidade.** Só máquinas autorizadas executam a operação. Alternativa não cria outro molde: máquina e ferramenta não podem executar trabalhos incompatíveis simultaneamente. Transferir trabalho exige recalcular OEE, duração, setups e recursos.

**Pessoas.** Setup consome equipa de setup; produção consome operadores do grupo/turno. Insuficiência pode exigir aprovação e ação operacional; não demonstra ser possível produzir sem pessoas. Reduções de capacidade devem usar calendário/bloqueios: a validação rejeita capacidade específica de máquina ativa diferente da soma dos turnos.

## 4. Lotes, OEE e coprodução

**Dimensionamento.** Percorre necessidades datadas, usa excedentes anteriores e cria lotes. Correções por SKU podem alterar eco-lote, mínimos de quantidade/tempo, agrupamento, prioridade e buffers; distinguir origem ISOP do valor efetivo.

```text
Quantidade = teto(necessidade ajustada / eco-lote) × eco-lote
Cadência efetiva = peças/hora nominais × OEE efetivo
Produção (min) = quantidade / cadência efetiva × 60
Setup (min) = setup configurado em horas × 60
```

Sem eco-lote positivo, mantém a quantidade solicitada. Necessidade 2 500 e eco-lote 1 000 originam 3 000 peças; as 500 excedentes cobrem procura posterior, não representam duplicação.

**OEE.** Fator configurado, não medição de eficiência real. Base **0,66**, com override por máquina. Exemplo: 2 400 peças a 1 200 peças/hora e OEE 0,66 requerem **181,82 minutos**; com 30 de setup, **211,82 minutos** de carga. Mínimo produtivo atual: 1 minuto.

**Gémeas.** Um ciclo gera dois outputs 1:1. Eco-lotes efetivos têm de ser iguais. O emparelhamento admite necessidades até cinco índices diários de distância, não cinco dias úteis. Após arredondamento:

```text
Quantidade comum = máximo(quantidade A, quantidade B)
Tempo do ciclo = máximo(tempo A, tempo B), não a soma
Setup comum = máximo(setup A, setup B), não a soma
```

Ambos recebem a quantidade comum. Sem procura oposta elegível, o segundo output é stock coproduzido: cobre procura futura, mas não cria entrega fictícia. Se subcontratado, só fica disponível para cliente após o lead externo.

**Material das gémeas.** O lote físico partilha o release mais cedo dos outputs e o prazo produtivo mais cedo relevante. É regra de coprodução, não autorização para antecipar referências independentes.

**Conservação.** Dividir um lote em turnos/dias não altera quantidade; arredondamentos compensam-se no fragmento final. Validam-se segmentos contra lotes e lotes contra necessidades, incluindo gémeas. Omissões, duplicações ou excesso face aos lotes previstos bloqueiam aplicação, mesmo com bons indicadores.

## 5. Setups, material e subcontratação

**Afinação.** Independentes usam molde + SKU; gémeas confirmadas partilham ciclo; família explícita permite referências sucessivas com afinação comum. **Mesmo molde não basta para dispensar setup.** Família não é coprodução. JDE002 está configurada para `TP042173-0040-1` e `TP042173-0060-2`, não todas as referências do molde.

O tempo segue exceção referência/máquina, depois ferramenta/operação e fallback de 0,5 h. Setup suficiente precede e permanece ligado à produção; outra ferramenta não pode intercalar-se. Turnos/noites/dias fechados não exigem automaticamente nova afinação. Setup isolado, posterior, duplicado ou desligado bloqueia aplicação.

**Material: invariante.** Antes de cinco dias úteis da referência de material, **setup e produção são proibidos**. Dentro da janela, ocupar o primeiro intervalo operacionalmente admissível. É restrição bloqueante, não preferência de scoring.

```text
Artigo normal:
  referência de material = entrega ao cliente
  libertação = entrega − 5 dias úteis

Artigo subcontratado:
  envio = entrega − lead útil externo − buffer externo
  referência de material = envio
  libertação = envio − 5 dias úteis
```

Fins de semana fechados/feriados não contam; aberturas extraordinárias afetam o calendário. Sem feriados, entrega à sexta-feira liberta material na sexta-feira anterior. Setup na quinta-feira anterior ao release é inválido, mesmo produzindo depois.

**Subcontratação.** Distinguir fim interno, envio e disponibilidade para cliente. Fornecedor genérico atual: **5 dias úteis** de lead, buffer zero. Entrega à sexta-feira exige envio na anterior; o release recua mais cinco dias úteis. OTD/OTD-D usam disponibilidade após o lead, não apenas fim interno.

A janela impõe limite inferior, não garante toda a carga até ao prazo. Pode existir atraso em `best_effort`, sem antecipar material. Release anterior a D0 conserva-se, mas não permite execução antes do horizonte. Buffers internos mudam objetivos, não a data comercial nem a autorização de material.

## 6. Prioridades e espaços vazios

**Regra funcional final:**

1. Antes da janela dos cinco dias úteis: setup e produção proibidos.
2. Dentro da janela: produzir o mais cedo possível.
3. Um espaço vazio só permanece com razão operacional demonstrável.
4. **OTD e OTD-D nunca pioram para tornar o plano visualmente mais compacto.**

**Prioridade.** Considera prazo produtivo controlável, rutura, prioridade explícita e campanha. Subcontratação pode antecipar urgência face à entrega comercial. Existe prioridade 100 para `TP042173-0040-2`; não autoriza material antecipado nem conflito físico.

| Razão para um espaço | Evidência |
| --- | --- |
| Material não libertado | Release e lote |
| Fecho/indisponibilidade | Calendário, recurso, intervalo e motivo |
| Ferramenta/equipa ocupada | Ocupação concorrente e grupo |
| Operadores insuficientes | Turno, procura e disponibilidade |
| Prioridade / setup incompatível | Prazos e sequência física |
| Antecipação prejudica entregas | Indicadores antes/depois e compromissos afetados |
| Final de campanha | Elegibilidade e resultado validado |

Procura-se antecipar lotes ou fragmentos, conservando quantidades, tempos e outputs; reavaliam-se oportunidades após movimentos. `left_shift_opportunities` conta oportunidades acionáveis, não minutos vazios. Zero é ausência detetada na pesquisa, não prova de ótimo global.

**Exceção de campanha.** Produção curta associada a família confirmada pode passar para o último turno do dia final da campanha longa. Limite normal: 40% desse turno, atualmente 200 minutos, sem aumentar setups. Pode manter espaço anterior por decisão operacional, não impossibilidade física. Um ramo limitado para plano incompleto preserva percentuais protegidos, mas admite até +1 dia de atraso agregado, +1 dia útil produtivo e aumento limitado do défice, com aviso.

**Diferença atual.** `delivery_not_worse` compara indicadores lexicograficamente: melhorar uma prioridade anterior pode compensar piorar outra. Preenchimento canónico de gaps e normalização de prioridades não acrescentam guardas independentes de OTD/OTD-D. A regra final acima é o requisito; **a proteção individual ainda não está explicitamente garantida em todos esses caminhos**. O manual documenta, não altera o algoritmo.

## 7. OTD: entregas por lote

**Cálculo para artigos normais:**

1. Divide as necessidades ISOP em lotes de produção.
2. Para cada lote, procura o último dia com produção desse lote.
3. Compara-o com a data comercial de entrega/expedição associada.
4. Terminando no próprio dia ou antes, está a tempo.
5. Terminando depois, está atrasado.

```text
OTD (%) = lotes concluídos a tempo / total de lotes × 100
        = (1 − lotes atrasados / total de lotes) × 100
```

| Lote | Entrega | Conclusão | Resultado |
| --- | --- | --- | --- |
| L1 | 09-Out | 08-Out | A tempo |
| L2 | 09-Out | 09-Out | A tempo |
| L3 | 09-Out | 12-Out | Atrasado |
| L4 | 12-Out | 09-Out | A tempo |

Neste exemplo: **OTD = 3 / 4 × 100 = 75,0%**.

**Unidade.** Todos os lotes têm o mesmo peso, independentemente de peças/faturação. Um lote de 100 e outro de 100 000 peças contam uma vez cada. Uma referência com vários lotes conta várias vezes; fragmentar segmentos não aumenta o denominador. Arredondamento: uma casa decimal.

**Dia, não hora do camião.** Terminar no dia da entrega conta como pontual; não garante uma hora de corte nesse dia. Um segmento apenas de setup não conclui o lote.

**Subcontratação.** A conclusão relevante inclui lead útil externo até disponibilidade para cliente. Terminar internamente na data comercial pode já ser atraso; envio externo tem acompanhamento próprio.

**Gémeas.** Avaliam-se outputs com necessidade comercial; basta um atrasado para o lote contar como atrasado. Stock coproduzido sem entrega não cria compromisso fictício.

**Cobertura separada.** Sem lotes, a fórmula devolve 100%, significando ausência de elementos a avaliar. Lotes/quantidades omitidos são verificados separadamente e bloqueiam. Uma percentagem arredondada de 100,0% não dispensa conferir contadores de falhas.

## 8. OTD-D, stock e outras métricas

**OTD-D mede checkpoints, não peças.** Para cada operação/dia com necessidade positiva, compara disponibilidade acumulada com necessidade acumulada. Dias sem necessidade não criam checkpoints; a produção nesses dias pode cobrir procura futura.

```text
Checkpoint = operação + dia com necessidade positiva
Cumprido se disponível acumulado >= necessidade acumulada
OTD-D (%) = checkpoints cumpridos / total de checkpoints × 100
```

| Checkpoint | Necessidade acumulada | Disponível | Estado |
| --- | --- | --- | --- |
| A, dia 1 | 100 | 100 | Cumprido |
| A, dia 2 | 200 | 150 | Falha de 50 |
| A, dia 3 | 300 | 300 | Cumprido |
| B, dia 3 | 200 | 200 | Cumprido |

**OTD-D = 75,0%.** Recuperar no dia 3 não apaga a falha do dia 2. Usa NP líquida sem somar novamente stock inicial. Fornecimentos comprometidos entram no respetivo dia; gémeas na operação correta; subcontratação após lead útil. Arredonda a uma casa decimal, entre 0 e 100%.

**Diferença.** OTD exige terminar o lote; OTD-D pode reconhecer produção parcial. Um lote pode cobrir várias datas. OTD-D não é percentagem de peças ou encomendas prontas.

| Indicador | Leitura |
| --- | --- |
| `tardy_count` | Número de lotes atrasados |
| `total_tardiness` / `max_tardiness` | Soma / máximo em índices diários, normalmente dias corridos |
| `production_due_misses` | Lotes após o prazo produtivo controlável |
| `production_due_late_workdays` | Atraso produtivo agregado em dias úteis |
| `subcontract_dispatch_misses` | Outputs comerciais com envio externo atrasado |
| `otd_d_cumulative_shortfall_qty` | Soma de défices nos checkpoints; pode repetir a mesma falta |
| `otd_d_final_shortfall_qty` | Défice que resta no final |

**Stock projetado** = disponibilidade acumulada − necessidade líquida acumulada. Negativo é rutura prevista, não contagem física. Entregas distribui peças cronologicamente sem prometer as mesmas a vários clientes. Setups contam campanhas com preparação positiva; tempo de setup soma minutos dos segmentos.

## 9. Qualidade, gates e robustez

**Trust Index.** Qualidade da entrada: completude 25%, validade 30%, consistência 25%, riqueza 20%. Recomenda automação total ≥90; monitorização 70–89; sugestão 50–69; manual <50. Não é OTD nem certificação do Excel: alguns fallbacks precedem a avaliação.

| Gate | Efeito da falha |
| --- | --- |
| Física: máquina, molde, equipa, calendário, elegibilidade e setup | Bloqueia |
| Cobertura: lotes, origem ISOP, quantidades e gémeas | Bloqueia |
| Material: setup ou produção antes do release | Bloqueia |
| Sequência: oportunidades acionáveis e inversões/interrupções reparáveis | Bloqueia |
| Entrega: OTD/OTD-D 100%, zero atrasados e zero checkpoints falhados | Exige aprovação |
| Envio externo, operadores ou produção longa | Exige aprovação |

**Decisões.** `auto_applicable`: pode aplicar; `approval_required`: admite exceções; `blocked`: não aplica. Aprovar risco comercial não permite sobreposição, falta de quantidade ou material antecipado. `best_effort` é melhor plano admissível encontrado, não ótimo/todas as entregas cumpridas. Aprovação associa motivo, autor, candidato e revisão.

**Produção longa.** Verifica lotes com índices diários consecutivos de produção superiores a `max_run_days`, atualmente 4. Fim de semana sem produção interrompe a sequência; não é duração total da campanha nem quatro dias úteis consecutivos.

**Robustez (só informação, decidido em 07/10/2026).** Reproduz o plano fixo sob perturbações, sem reotimizar cada amostra. Nunca ordena candidatos, nunca bloqueia, nunca pede aprovação e nunca altera o plano. Depois de cada gravação corre automaticamente em segundo plano (modelo v5, 500 cenários) e mede só os próximos 10 dias úteis a partir de hoje ou do dia de congelamento; pausa enquanto há planeamento a correr. `PP1_AUTO_ROBUSTNESS=0` desliga o cálculo automático; o painel continua a permitir execuções manuais de 100, 500 ou 2 000 cenários. Sucesso = cenário com zero lotes atrasados na janela; probabilidade = sucessos / cenários concluídos × 100. Se não houver entregas nessa janela, o resultado diz isso e não mostra probabilidade (nunca 100%). Não implica OTD-D 100% nem aprovação de todos os gates.

«OTD P95» é Q5 do OTD, a cauda inferior; «atrasados P95» é Q95 da contagem, podendo ser fracionário. CVaR95 é média dos atrasos totais a partir de Q95, incluindo empates; não são intervalos de confiança. Confirmar a revisão avaliada.

Planos que antes paravam só por «robustez não avaliada», incluindo movimentos manuais com todas as validações limpas, aplicam-se agora diretamente.

## 10. Ecrãs: Hoje e Plano

Plano: sequência por máquina, datas, validações e comandos. Dados exemplificativos de 16-09-2026. (captura local não incluída).

**Navegação.** Hoje, Plano, Carga e capacidade, Entregas, Risco e Configuração. Cabeçalho: ISOP, indicadores, trocar ficheiro, atualizar consultas, recalcular e Copilot. Indicadores abrem Entregas sem filtro específico. Recalcular fica indisponível durante cenário simulado ativo.

**Hoje.** Navega por dia; mostra estado, máquinas, ocupação, produção, setups atuais/seguintes, indisponibilidades, expedições e riscos com «Abrir no plano». «Agora» e fim previsto usam calendário/data, não execução confirmada.

**Plano.** Gantt/Tabela; pesquisa, máquina, inativas, zoom 50–300%, períodos, turnos e navegação temporal. Gates, cores por ferramenta, setup, bloqueios e marcos. Selecionar abre detalhe: quantidades, tempo, material, envio e explicação. A tabela permite ordenar/pesquisar; quantidade do segmento não é total do lote.

**Ações.** CSV, versões em Planos, mover produção e Simular alterações. CSV respeita datas, não todos os filtros, e inclui KPIs globais. Banners identificam cenário/edição manual; reverter depende de estado anterior recuperável. Editar/Consulta limita comandos, mas **não autentica utilizadores**.

## 11. Ecrãs: Carga, Entregas e Risco

Entregas por referência: stock e risco de rutura. Dados exemplificativos de 16-09-2026. (captura local não incluída).

**Carga e capacidade.** Grelha diária/semanal: produção, setup, capacidade livre e excesso. Azul: produção; laranja: setup; cinzento: livre; tracejado: fechado; vermelho: sobrecarga. Semanas usam dias efetivamente abertos. Inclui operadores por grupo/turno. Consulta sem editor, redistribuição ou exportação própria; livre não significa elegível.

**Entregas por referência.** Stock projetado, primeira rutura e detalhe. Filtros por cliente, máquina, rutura e procura; sem pesquisa textual própria. Saldo final positivo não apaga rutura intermédia.

**Por encomenda.** Agrupa por data/cliente: quantidade, cobertura, conclusão e estados pronto, parcial, no subcontratante, em produção, planeado ou não planeado. Taxa de preparação, risco a cinco dias e cobertura global. Não regista expedição física/stock real; não liga diretamente aos IDs dos lotes de suporte.

**Risco.** Visão geral, Atrasos e Equipa: saúde, mapa máquina/dia, restrições, atrasos e operadores. Saúde 80–100: estável; 50–79: atenção; <50: crítico. Margem é distância entre conclusão e prazo. Scores de risco diferem de Trust Index, OTD e robustez.

## 12. Ecrã: Configuração

Configuração: fábrica, recursos, calendários e administração. Fotografia de 16-09-2026. (captura local não incluída).

**Fábrica.** Máquinas: adicionar, grupo, OEE e ativação; desativar conserva histórico. Turnos: editar os existentes, sem adicionar/remover. Operadores: efetivos por grupo/turno; equipas de setup são distintas.

**Ferramentas/artigos.** Consulta artigos/máquina principal; edita alternativa/setup, sem botão adicionar ferramenta. Exceções por referência/máquina; gémeas confirmadas com eco-lotes coerentes. Subcontratação: referências e lead útil, entidade genérica/buffer zero, sem gestão de fornecedores. Famílias de setup não têm editor dedicado normal.

**Calendário.** Feriados, encerramentos, dias extra e indisponibilidades por recurso/intervalo/motivo. Alteram capacidade e marcos úteis; manutenção parcial bloqueia só horas relevantes.

**Administração.** Qualidade, tabela ISOP, correções por SKU e parâmetros: OEE, eco-lote, buffers, mínimos, agrupamento e prioridade nos campos suportados. Perfis Urgente, Equilibrado, Menos setups e Mais entregas a tempo não suspendem material/restrições físicas.

**Guardar.** Máquinas, ferramentas, turnos, equipas de setup e indisponibilidades: calcular → rever → **Aplicar e guardar**. Parar/cancelar abandona proposta. Outros formulários gravam/recalculam diretamente. Confirmar revisão e resultado aplicado.

## 13. Movimentos, simulações e promessa

**Mover.** Selecionar no Plano; escolher máquina/dia/início; pedir preview; rever conflitos, setups, quantidades, marcos e indicadores; aplicar candidato validado. Afeta o lote e a sequência, não só a barra. Arrasto arredonda a 15 minutos; formulário permite início produtivo exato. Aplicação confere dataset/revisão/destino; degradação comercial exige motivo/aprovação nesse fluxo. Cria âncora de destino; não há gestor visual autónomo de locks.

| Simulação | Hipótese |
| --- | --- |
| Antecipar/atrasar EDD | Data da necessidade |
| Parar máquina / bloquear ferramenta | Recurso, período e motivo |
| Falta de operadores | Grupo, turno, pessoas e intervalo |
| Horas extra / feriado | Capacidade e calendário |
| Encomenda urgente / alteração / cancelamento | Quantidades e necessidades |
| Forçar máquina / alterar OEE | Rota e duração |
| Alterar eco-lote | Dimensionamento |

**Efeitos.** Simular calcula sobre cópias, sem alterar plano. **Aplicar no Gantt substitui o estado ativo partilhado no servidor**, atualiza análises e pode persistir configuração, mantendo indicação de cenário/reversão. Não é vista privada. Guardar cenário conserva alternativa; aplicar como realidade usa o respetivo fluxo/gates.

Mudar data comercial altera a hipótese, não melhora cumprimento do compromisso original. «Dia» pode ser índice D0, D1, etc.; conferir datas reais.

**Paragem rápida.** Tenta aplicar diretamente, sem preview separado nem job cancelável próprio. Para estudar primeiro impacto, usar simulação completa. Rever transferências, setups, pessoas e entregas.

**CTP: Posso prometer?** Indicar referência, quantidade e prazo; avalia encaixe, material, duração e subcontratação. Não reserva capacidade nem envia promessa ao cliente. Aplicar necessidade é separado e valida impacto nos compromissos existentes. Resultado perde validade quando muda procura/configuração/revisão. Alguns fluxos diretos devolvem HTTP 409 se faltar aprovação exigida.

## 14. Operação, versões e assistência

**Rotina.** Confirmar ISOP/data em Hoje; rever recursos, preparações e expedições; abrir riscos no Plano; conferir material, prazo e envio; consultar falta por cliente em Entregas; tratar causa ou calcular alteração. OTD elevado pode esconder atraso prioritário; máquina vazia pode aguardar material.

**Planos.** Lista versões, origem e indicadores; guarda versão nomeada, restaura e elimina conforme o modo. Snapshot inclui dados, configuração, lotes, segmentos, gates, avisos, edições e aprovações. Restauro valida modelo/política atuais e pode recalcular; não garante minutos idênticos de uma versão incompatível. Reverter/Desfazer usa estado anterior, não histórico infinito. Normalmente conserva vinte versões automáticas; manuais ficam fora da poda.

**Journal e Regras.** Em Configuração → Administração/Avançado: «Diagnóstico» mostra severidade, fase, mensagem e duração, sem pesquisa/exportação nem auditoria completa por pessoa. «Ver regras» tem 19 descrições frontend, parcialmente configuradas: não é editor nem inventário exaustivo. Regras textuais do Copilot são contexto, não restrições matemáticas automáticas.

**Copilot.** Consultas, visualizações e ações por ferramentas backend, dependentes do provider. Indisponibilidade não impede os ecrãs industriais. Ações estão sujeitas a gates. Chat sem streaming, anexos ou histórico persistente; fechar perde conversa local. Nem todas as ações atualizam vistas: confirmar plano/revisão.

| Sintoma | Verificação |
| --- | --- |
| OTD diferente de OTD-D | Lotes completos versus checkpoints/produção parcial |
| Produção concluída, entrega não pronta | Lead externo ou peças atribuídas a entrega anterior |
| Espaço / setup inesperado | Material, calendário, recursos e identidade de afinação |
| Mudança não aparece | Aplicação do candidato, revisão e atualização/reabertura |
| Plano válido pede aprovação | Entrega, envio externo, pessoas e produção longa (robustez não pede aprovação) |
| Timeout / candidato obsoleto | Estado do mesmo job e alteração da origem |

## 15. Motor e arquitetura

```text
ISOP + configuração + calendário
  -> operações -> lotes/gémeas -> campanhas
  -> construção -> pesquisa/polimento -> reparações
  -> score + gates + explicações
  -> candidato -> aprovação quando exigida -> aplicação
  -> robustez em segundo plano (só informação)
```

**Construção.** OR-Tools CP-SAT concilia recursos/janelas; tenta serviço estrito e admite atraso em fallback, sem relaxar material. Existe construção heurística. VNS pesquisa ordem, reposicionamento e alternativas; CPO coordena candidatos e polimento. Normalização trata gaps, prioridades, alternativas e final de campanha.

**Escolha.** Serviço usa comparação lexicográfica; setups, utilização e antecipação são secundários sujeitos a gates. Não substitui proteção independente dos indicadores na compactação. Timeout não prova inviabilidade; melhor candidato não prova ótimo global. Pesquisa tem limites de tempo, passagens e movimentos.

| CPO | Pesquisa nominal | Candidatos adicionais | Polimento/máquina |
| --- | --- | --- | --- |
| quick | 60 s | 0 | Desativado |
| normal | 60 s | Até 12 | 1 s |
| deep | 300 s | Até 48 | 5 s |
| max | 600 s | Até 80 | 20 s |

Construção, análises e persistência podem aumentar duração total; a robustez corre depois, fora do orçamento. Aprendizagem/Optuna/pesquisa genética existem em caminhos específicos, não obrigatórios em cada upload. Conservar ficheiro, configuração, código, opções e sementes para reproduzir.

**Tecnologia.** React 19/TypeScript/Vite/Zustand; API FastAPI/Pydantic/Uvicorn; openpyxl; YAML; Python/OR-Tools; SQLite; OpenAI/Ollama opcionais. Docker usa Nginx/Supervisor. Python de referência: **3.12**; metadados legados ≥3.10 não provam compatibilidade.

**Concorrência.** Plano e locks são locais ao backend e partilhados. Usar **uma instância com um worker API** sem coordenação adicional. Upload/replaneamento têm jobs; simulação/CTP e outros caminhos síncronos podem bloquear pedidos. Cancelamento cooperativo; HTTP 202 significa aceite, não aplicado. Revisão, dataset e fingerprints protegem contra candidatos obsoletos.

## 16. API, persistência e implantação

| Domínio | Rotas representativas |
| --- | --- |
| Dados/análises | `/api/data/score`, `/segments`, `/lots`, `/stock`, `/orders`, `/capacity`, `/risk`, `/gate-report` |
| Upload/recálculo | `/api/data/load/prepare`, `/load/confirm`, `/load/jobs/{id}`, `/replan-jobs` |
| Movimento | `/api/data/plan/move-preview`, `/move-preview-jobs`, `/move-apply`, `/edits` |
| Cenários/CTP | `/api/data/simulate`, `/simulate-apply`, `/scenarios`, `/ctp`, `/ctp-apply`, `/revert` |
| Configuração | `/api/data/config`, `/machines`, `/tools`, `/operators`, `/subcontracts`, `/holidays`, `/unavailability` |
| Versões/robustez | `/api/data/plans`, `/robustness-runs` |
| Operação/assistente | `/api/console`; `/api/copilot/chat`, `/health` |

Abreviações mantêm prefixo do domínio; movimento mantém `/api/data/plan`. Métodos/schemas: routers/OpenAPI. Upload legado por caminho local `/api/copilot/load` está desativado, HTTP 410.

**Armazenamento.** `config/incompol.yaml`: mestre; `config/factory.yaml`: fábrica efetiva. Em `data/`: `plans.db`, snapshots/cenários/uploads; `replan.db`, tarefas; `robustness.db`, avaliações; `audit.db`, decisões; `learning.db`, estudos; `copilot_state.json`, contexto textual.

**Durabilidade.** Snapshot e recibo de upload partilham transação SQLite antes da publicação. Não há transação global entre memória/YAML/bases. Falha de autosave noutros caminhos pode coexistir com memória alterada: confirmar versão guardada. Excel é temporário; **snapshot não substitui arquivar ISOP original**.

**Reinício.** Recupera versão persistida utilizável, com validação/eventual recálculo. Tarefas incompletas falham/são interrompidas, sem retoma automática. Previews manuais em memória têm de ser refeitos.

**Implantação.** API `backend.api.copilot:app`. Compose publica porta 3000 e conserva `/app/data`, não `/app/config`. Recriar contentor pode perder YAML alterado. Backup inclui dados, configuração e ISOPs. Saúde e `has_data` distinguem serviço de plano disponível. Consulta não autentica: segurança/identidade empresariais exigem proteção adicional.

## 17. Limitações e critérios de aceitação

**Limitações relevantes:**

1. Proteção individual de OTD/OTD-D por compactação não está explícita em todos os caminhos. Final de campanha pode manter espaço e admitir pequenos aumentos de atraso/défice.
2. Alguns rótulos dizem «dias úteis» para índices de calendário. `compact_enabled` não desativa preenchimento legal obrigatório; `eco_lot_mode=soft` não comprova algoritmo operacional distinto.
3. Datas ISOP devem ser diárias/contíguas; validação não é exaustiva. Fallbacks, como cadência inválida substituída, podem preceder DQA; conferir origem/avisos.
4. Upload assume máquinas livres e aprovação técnica automática. Aplicações diretas podem receber HTTP 409 por aprovação em falta. Rótulo «Requer aprovação» não prevalece sobre `apply_decision=blocked`.
5. Atualizar global pode não refazer consultas locais. CSV não replica todos os filtros; Regras não enumera todo o motor; Copilot pode exigir atualização. Consulta tem diferenças de permissões frontend/backend.
6. Plano partilhado sem autenticação empresarial nem execução/stock reais. Estado local impede múltiplos workers sem coordenação; persistência não é global e YAML precisa de preservação no Docker.

**Aceitar alterações exige evidência:**

| Critério | Verificação |
| --- | --- |
| Quantidades | Sem omissões, duplicações ou excedentes inesperados |
| Recursos/calendário | Sem conflitos; turnos e bloqueios respeitados |
| Material/setup | Nada antes do release; preparação suficiente e ligada |
| Compactação | Comparar OTD e OTD-D separadamente; nenhum piora |
| Exceções | Motivo, autor técnico, candidato e revisão identificados |
| Comparação | Mesma origem, exceto hipóteses explicitamente alteradas |
| Recuperação | Snapshot consistente; restauro verificado se afetado |
| Explicação | Causa concreta de atrasos, espaços e movimentos |

Manual produzido por inspeção de código/testes e consulta dos ecrãs, sem alterar regras nem executar nova certificação integral do algoritmo. Mudanças futuras devem atualizar implementação, testes e documento. Testes que escrevem configuração/snapshots devem correr isoladamente.

## 18. Referência técnica e manutenção

**Pontos de entrada.** Caminhos relativos à raiz; implementação atual prevalece sobre comentários históricos. Este índice localiza o detalhe sem o repetir no manual compacto.

| Assunto | Ficheiros / módulos |
| --- | --- |
| ISOP/NP/agregação | `backend/parser/isop_reader.py`; `backend/transform/` |
| Calendário/fábrica | `backend/calendar.py`; `backend/config/`; `config/factory.yaml` |
| Lotes/gémeas | `backend/scheduler/lot_sizing.py`; `backend/config/planning.py` |
| Afinação/material | `backend/scheduler/setup_identity.py`; `jit_policy.py`; `validation.py` |
| Prioridades/gaps | `backend/scheduler/priority.py`; `gap_filling.py`; `priority_normalization.py`; `campaign_tail.py`; `operational_audit.py` |
| OTD/OTD-D | `backend/scheduler/scoring.py`: `compute_score`, `_compute_otd_d`, `_customer_delay_for_output` |
| Gates/otimização | `backend/scheduler/gates.py`; `global_jit.py`; `vns.py`; `backend/cpo/optimizer.py` |
| Análises/risco | `backend/analytics/`; `backend/risk/robustness.py`; `jobs.py` |
| Estado/jobs/restauro | `backend/loading/`; `backend/replan/`; `backend/plans/`; `backend/copilot/state.py` |
| API/interface | `backend/api/`; `frontend/src/pages/`; `frontend/src/components/` |
| Testes | `tests/test_scheduler.py`; `test_gap_filling.py`; `test_campaign_tail.py`; `test_plans.py`; `test_load_jobs.py`; `test_robustness.py` |

**Vocabulário.** APS: planeamento com restrições; EDD: prazo de ordenação; OEE: eficiência; release: libertação; SUBC: subcontratação; JIT: nome histórico da janela; CP-SAT: solver; VNS: pesquisa local; CPO: orquestrador; CTP: capacidade para prometer; gate: validação; stale: obsoleto; fingerprint: hash de coerência.

**Referência.** Política `setup-families-v1`; snapshot `aps-v5`, serialização 4. Conservar código/configuração/ISOP/sementes. A existência de teste não significa execução nesta entrega.

**Manutenção.** Atualizar data/edição ao mudar fórmula, regra, ecrã ou fluxo. Fonte: `docs/manual-tecnico-funcional-incompol.md`; gerador: `docs/tools/render_manual.py`. Word/PDF partilham conteúdo; capturas são exemplos. Limite editorial: **20 páginas, incluindo capa e índice**.
