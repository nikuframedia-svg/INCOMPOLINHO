# Fecho do feedback PDF: objetivos 6, 9, 10 e 11

## Objetivo 6: pagina Hoje

- O resumo diario deixa de depender de frases genericas como "Sem problemas" quando existem atrasos, ruturas ou risco operacional.
- A utilizacao textual passa a usar capacidade real disponivel da maquina no dia, incluindo calendario, feriados, fins de semana e indisponibilidades.
- Os setups sao apresentados por horizonte e turno: hoje / amanha e Turno A / Turno B.
- As expedicoes continuam agregadas num quadro unico com hoje e amanha.

## Objetivo 9: libertação simulada de material e produções antecipadas

- A janela de 5 dias úteis passa a ser regra bloqueante de libertação simulada:
  antes da entrega ao cliente nos artigos normais e antes do envio planeado ao
  fornecedor nos artigos subcontratados.
- Depois da libertação, a produção é puxada para o primeiro espaço físico
  possível, dando prioridade à rutura e ao OTD.
- Planos com producoes antecipadas acima da janela nao podem ser aplicados silenciosamente.
- O gate devolve estado `jit_window_blocked`, com `apply_decision=blocked`.
- A regra de 4 dias consecutivos continua como best-effort/alerta operacional.
- Snapshots de políticas anteriores são preservados como histórico e
  recalculados antes de poderem voltar a ser aplicados.

## Objetivo 10: What-if

- A simulacao passa a expor cenarios separados para maquina parada, ferramenta/molde indisponivel, falta de operadores, horas extra e terceiro turno.
- Cada cenario apresenta campos especificos: recurso, inicio/fim, turno, quantidade de pessoas e motivo quando aplicavel.
- O preview inclui impacto em OTD, OTD-D, atrasos, violacoes JIT, setups e ocupacao media.
- A aplicacao de cenarios fica bloqueada quando o gate devolve `jit_window_blocked`.

## Objetivo 11: Carga/capacidade e risco

- A pagina Carga e capacidade continua a usar capacidade real semanal, excluindo dias fechados.
- A legenda foi clarificada: azul producao, laranja setup, cinzento sem carga, tracejado fechado, vermelho carga acima da capacidade.
- `100% completa` e tratado como ocupacao total normal; vermelho fica reservado para `load_min > cap_min`.
- O heatmap de risco passa a expor valores/tooltip com risco, utilizacao, carga, capacidade, dia e maquina.
- O risco usa a mesma capacidade real que Carga/capacidade e Gantt.

## Perfis funcionais

- O modo Consulta permite leitura e previews/simulacoes.
- O modo Editar permite guardar, recalcular, aplicar cenarios e alterar configuracao.
- Chamadas mutaveis em modo Consulta sao bloqueadas no frontend e rejeitadas no backend via header `X-Access-Mode: view`.

## Estado observado apos implementacao

- O plano persistido atual carrega com dados visiveis.
- Como contem 16 violacoes da janela JIT, fica bloqueado por `jit_window_blocked`.
- Isto esta conforme a nova regra: plano invalido por antecipacao nao e aceite silenciosamente.
