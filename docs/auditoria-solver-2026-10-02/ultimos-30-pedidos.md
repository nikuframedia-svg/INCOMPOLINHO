# Os 30 pedidos de utilizador mais recentes sobre INCOMPOLINHO

Recolha: 02/10/2026. Foram lidos 106 turnos de duas conversas relevantes e encontradas 40 mensagens de utilizador; a tabela retém as 30 mais recentes. As datas abaixo usam Europe/Lisbon. Não são os últimos 30 commits nem 30 erros diferentes. Mensagens de estado e continuação foram mantidas para tornar a seleção auditável.

Fontes: **T1 — Executar INCOMPOLINHO localmente**, chat `019fad87-d6e7-7df0-9e75-ab52cd6aea0c`; **T2 — Esclarecer parâmetros de data**, chat `01a0857b-c124-78d2-a49d-46093d8ccc65`. Respostas anteriores são relatos históricos, não prova independente. Só BFP186/revisão 90 e os contraexemplos de comparação foram reproduzidos nesta auditoria.

| # | Data/hora | Pedido, em síntese | Evidência/contexto | Regra ou caso de teste |
|---|---|---|---|---|
| 1 | 02/10, 19:50 | Recalcular e procurar antecipações restantes | BFP181 corrigida no histórico; BFP186 ainda antecipável. Esta auditoria reproduziu BFP186 na revisão 90. | N1, comparação temporal, prova no candidato completo |
| 2 | 02/10, 19:44 | Resumo do trabalho | Pedido de estado; não introduz uma regra nem um defeito novo. | Distinguir código publicado de plano substituído |
| 3 | 01/10, 21:03 | Estado do trabalho | Pedido de estado; o relato anterior refere rejeição incorreta pelo fim do lote. | Medir serviço por encomenda, não apenas fim agregado |
| 4 | 01/10, 16:27 | Encontrar e explicar a causa raiz | O relato distingue ocupação real da equipa na revisão 75 de espaço libertado posteriormente com posições preservadas. | Explicação ligada à revisão e ao calendário |
| 5 | 01/10, 16:23 | A que se referem os erros | Foram distinguidos oportunidade perdida, fixação manual e impedimento físico. | Taxonomia de causas com evidência |
| 6 | 01/10, 16:20 | Produções que não começam mais cedo no dia | BFP080 tinha alternativa antecipada; BFP083 tinha início manual às 15:30. Diagnósticos históricos, não reexecutados aqui. | Antecipação por eventos e respeito por âncoras |
| 7 | 01/10, 16:12 | Produzir VUL195/VUL174 em D8 | Relato: a mudança de BFP079 libertou D8, mas as restantes posições ficaram antigas. | Reavaliar vizinhos após libertar capacidade |
| 8 | 01/10, 16:04 | Confirmar responsabilidade pelo erro | Continuação do caso BFP082/BFP080. | Separar regressão de planeamento de falta física de capacidade |
| 9 | 01/10, 15:05 | BFP082 no dia zero antes de BFP080 | Histórico referido: reparação de operadores mudou sequência e a proteção posterior manteve-a. | Prioridade comercial e testes de não regressão |
| 10 | 01/10, 11:31 | Mostrar resultado na aplicação | Pedido de evidência visual do plano realmente aplicado. | Gantt e snapshot persistido coerentes |
| 11 | 29/09, 16:05 | Plano com mais detalhe num documento | Pedido de documentação de contexto e execução. | Plano durável e verificável |
| 12 | 29/09, 15:38 | Automatizar os pedidos recorrentes de antecipação | Pedido explícito para o sistema procurar os casos que o utilizador encontra visualmente. | Melhoria automática, não remendos por referência |
| 13 | 29/09, 15:36 | Implementar alternativas verificadas com regras estáveis | Plano antigo de movimentos comparativos; o pedido seguinte mudou o foco para automatização. | Partilhar alocação e avaliação entre movimentos e automático |
| 14 | 29/09, 12:41 | Solução estável sem mudar preferências em cada caso | Pedido conceptual e de pesquisa sobre sistemas semelhantes. | Um contrato versionado |
| 15 | 29/09, 12:28 | Porquê transferir BFP079 PRM031→PRM039 | Explicação inicial baseada em OEE era hipótese; depois foi comparada uma alternativa completa. | Comparação executável; OEE isolado não prova causalidade |
| 16 | 29/09, 12:15 | BFP112 começar no dia anterior | Relato: máquina livre 10:50, equipa 11:50, produção após setup; bloqueio antigo de feriado era desatualizado. | Eventos reais e invalidação das explicações |
| 17 | 29/09, 11:14 | Confirmar resolução estrutural | Relato limitava a correção ao percurso testado e preservava histórico. | Não generalizar uma regressão corrigida a todo o solver |
| 18 | 28/09, 17:23 | Aplicar a correção do intervalo BFP082 | Relato: revisão 83 antecipou a produção para 17:29, conservando 32 000 peças. | Alterar cronologia real, não só renderização |
| 19 | 28/09, 17:22 | Explicar o espaço que ficou | Setup visual removido, mas 75 minutos permaneceram no horário protegido. | Normalização após retirada de setup |
| 20 | 28/09, 13:13 | Retirar código/cartão «Sem prod.» | Rejeição explícita de novos cartões como resposta ao defeito. | Sem funcionalidades visuais para esconder a lacuna |
| 21 | 28/09, 12:46 | Atualizar correção visual e mostrar foto | Pedido de verificação no frontend. | Evidência visual não substitui validação física |
| 22 | 28/09, 12:45 | Porquê ainda aparece o intervalo | Relato distinguia algoritmo atualizado e snapshot antigo. | Identificar revisão, proteção e aplicação |
| 23 | 28/09, 12:06 | Faixa de setup desapareceu mas atraso permanece | Requisito de eliminar a espera real admissível. | Conservação + compactação + validação |
| 24 | 27/09, 23:09 | Pedido de duração/estado | Continuação da alteração do Resumo do Dia. | Não classificar como bug do solver |
| 25 | 27/09, 23:09 | Destacar recursos indisponíveis no Resumo do Dia | Alteração visual anterior; restrições de recurso devem ser coerentes com o plano. | Calendário partilhado por cálculo e apresentação |
| 26 | 25/09, 12:36 | Setup BFP082 com ferramenta mantida — causa estrutural | Diagnóstico histórico: perda de estado e normalização/validação insuficientes. | Identidade física de montagem |
| 27 | 25/09, 10:13 | Setup BFP082 com ferramenta mantida — outra conversa | Mesmo problema descrito noutro chat; pedido distinto, não defeito independente. | Deduplicar causas, manter rastreabilidade dos pedidos |
| 28 | 24/09, 13:10 | Corrigir estruturalmente troca entre turnos | Relato: BWI003 manhã/BFP186 tarde tornou-se candidato válido. | Trocas locais com equipas por turno |
| 29 | 24/09, 12:15 | Confirmar que a correção deve ser estrutural | Rejeição de um ajuste pontual para 08/10. | Vizinhança genérica e IDs renomeados |
| 30 | 24/09, 12:07 | Que código alterar para BWI003/BFP186 | Discussão de setup adicional e critérios de aceitação. | Incluir a decisão atual: antecipação antes de setups |

## Padrões que explicam a recorrência

1. Capacidade libertada não desencadeia sempre uma procura completa dos lotes afetados.
2. Antecipação no mesmo recurso e antecipação por alternativa pertencem a vizinhanças diferentes.
3. Estado físico de ferramenta/afinação perde-se nas fronteiras de histórico, campanha ou recálculo.
4. Mudanças no algoritmo, dados persistidos e aparência do Gantt são confundidas no relato de conclusão.
5. Há vários critérios de aceitação concorrentes; uma melhoria encontrada pode ser descartada noutra fase.
6. Algumas lacunas são proteções legítimas; a aplicação tem de as distinguir de restrições físicas e pesquisa inconclusiva.

A decisão nova de 02/10 nesta conversa não pertence à seleção retrospectiva: **a antecipação pode acrescentar setup se preservar entregas e restrições físicas; setups servem de desempate**. Substitui a política antiga que proibia esse aumento.

## Identificadores para rastreabilidade

| # | Chat | Turno |
|---|---|---|
| 1 | T1 | `01a0fdf3-eb0d-7f00-9c84-9ea3b0139267` |
| 2 | T1 | `01a0fdee-bb24-7632-9b17-ec78ab28f673` |
| 3 | T1 | `01a0f910-7118-7270-b6ac-ef927f8b8704` |
| 4 | T1 | `01a0f813-a9a3-7241-9151-cb784bae68e9` |
| 5 | T1 | `01a0f810-b2d6-7d73-a60b-d2c27702df00` |
| 6 | T1 | `01a0f80d-7599-75f2-be47-6d4ae6f27cc8` |
| 7 | T1 | `01a0f805-ed67-7943-98d5-d6fcbe51a519` |
| 8 | T1 | `01a0f7ff-1137-7523-8c6c-569419bc5e2d` |
| 9 | T1 | `01a0f7c9-373a-70c2-89e3-2edaaed7b693` |
| 10 | T1 | `01a0f704-7f4e-7cc0-8eb3-8178c9b0be94` |
| 11 | T1 | `01a0edb2-b6e6-7551-8e7d-96f7d620aaea` |
| 12 | T1 | `01a0ed99-fe7b-7963-b9f7-6aa697cdd565` |
| 13 | T1 | `01a0ed98-e4e7-7503-8f7b-7bd79b66ecc1` |
| 14 | T1 | `01a0ecf8-30d0-7e40-b03b-549fd894bb8a` |
| 15 | T1 | `01a0ecec-2cdd-7c11-9d6b-f6dff5f492cf` |
| 16 | T1 | `01a0ece0-ecf8-7e92-9537-0b0b54f7cde1` |
| 17 | T1 | `01a0eca8-7bba-7970-98eb-e43cdb9bc27f` |
| 18 | T1 | `01a0e8d4-549a-7e13-828e-15447c6a720f` |
| 19 | T1 | `01a0e8d3-4c32-7043-bdf8-b380ea9cf1ec` |
| 20 | T1 | `01a0e7ef-8100-73b1-82ca-ac661acff28c` |
| 21 | T1 | `01a0e7d6-31be-7432-8d53-00685d2db3fa` |
| 22 | T1 | `01a0e7d5-a847-73b2-b0c3-0bdcfb9a089c` |
| 23 | T1 | `01a0e7b2-4f38-7370-9dbf-67bed0eafa09` |
| 24 | T1 | `01a0e4ea-2337-7223-8a85-34018cb5785f` |
| 25 | T1 | `01a0e4ea-2337-7223-8a85-34018cb5785f` |
| 26 | T1 | `01a0d85a-35af-7e93-972b-b3dd9113bb55` |
| 27 | T2 | `01a0d7d7-4aef-7363-9b3d-a96b34e14a81` |
| 28 | T1 | `01a0d352-e905-7eb1-b576-073145077191` |
| 29 | T1 | `01a0d320-a6ad-71d0-9125-4fac8ec90d2a` |
| 30 | T1 | `01a0d319-0603-75f3-8e7a-6a15bdc92a2d` |

Vários pedidos podem ocorrer no mesmo turno. A seleção usa o tempo do turno e a ordem interna das mensagens, que é a precisão disponibilizada pela ferramenta de leitura.

