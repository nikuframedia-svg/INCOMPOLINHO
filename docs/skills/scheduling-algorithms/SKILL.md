---
name: prodplan-scheduling-algorithms
description: |
  Referência de algoritmos de scheduling e replaneamento.
  Usar para: implementar scheduler, regras de despacho,
  otimização, replaneamento, what-if, Monte Carlo.
---

# Algoritmos de Scheduling PP1

## ATCS (Apparent Tardiness Cost with Setups)
Prioridade(j) = (w_j / p_j) × exp(-max(slack_j,0) / (k1×p̄)) × exp(-s_prev,j / (k2×s̄))
- Termo 1: urgência/tempo (como WSPT)
- Termo 2: penaliza folga reduzida (OTD)
- Termo 3: penaliza setups longos
- k1, k2: parâmetros de sensibilidade (grid search 25-50 combos)
- Tempo: <10ms para 100 jobs × 5 máquinas

## Busca Local (refinamento)
SA: temp_inicial → arrefecimento → 10K iterações → 1-3 seg
Vizinhança: swap adjacente + insert + troca inter-máquina
Web Worker obrigatório. Melhoria: 5-15% sobre ATCS.

## Replaneamento por camadas
1. Right-shift: O(n), desloca operações, <30min perturbação
2. Match-up: reescalona até convergir com plano original, 30min-2h
3. Parcial: só operações afetadas (propagação por grafo), >2h
4. Regeneração: ATCS completo (<200ms), semente = plano anterior

## Triggers de replan
- Avaria máquina → right-shift + reroute
- Ordem urgente → resequenciar bottleneck
- Impossível 2 turnos → sinalizar turno noite

## Zonas de horizonte
- frozen (0-5d): freezeStatus='frozen', requer aprovação
- slushy (5d-2sem): freezeStatus='slushy', negociável
- liquid (resto): freezeStatus='liquid', livre

## Multi-objectivo (2 níveis)
Nível 1 (uso diário): lexicográfico com tolerância
  1º minimiza atraso, 2º minimiza setups com tolerância X%
Nível 2 (what-if): soma ponderada com sliders
  f = w_otd×T + w_setup×S + w_util×U (cada normalizado 0-1)

## Peças Gémeas no scheduler
- Identificar pares pela coluna M
- Quantidade = max(|NP_A|, |NP_B|)
- Tempo = quantidade / cadência (UMA vez, não dobro)
- Agendar como bloco único, output para ambos os SKUs

## Setup-dependente
- Agrupar SKUs em famílias por ferramenta (~8-15 famílias)
- Matriz de transição família×família
- ATCS usa termo exponencial com s_prev,j da matriz
- Busca local: delta de setup em O(1) via matriz
