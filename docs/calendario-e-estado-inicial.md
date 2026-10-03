# Calendario de ocupacao e estado inicial

## Ocupacao sem fins-de-semana

A ocupacao e a capacidade usam o calendario efetivo do horizonte:

- Segunda a sexta contam como dias uteis, salvo feriado ou ferias explicitas.
- Sabado e domingo ficam fechados mesmo quando nao aparecem em `holidays`.
- `extra_workdays` so reabre sabados ou domingos automaticos.
- Um feriado explicito ganha sempre sobre `extra_workdays`.
- Em agregacao semanal, `workday_count` conta apenas dias abertos; uma semana
  normal com 5 dias uteis e 2 dias de fim-de-semana conta 5.

## Estado inicial no carregamento

O carregamento de ISOP deixa de pedir preenchimento manual do estado de cada
maquina. A confirmacao suportada e explicita: todas as maquinas livres
(`mode: all_free`).

Contratos esperados:

- `/api/data/load/confirm` rejeita `mode: manual`.
- `/api/data/replan-jobs` rejeita payloads com `current_machine_states`.
- O frontend deve confirmar o ISOP preparado com `mode: all_free` e `states: []`.
