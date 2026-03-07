---
name: prodplan-domain-tests
description: |
  Gera testes que validam invariantes de domínio industrial.
  Usar para: escrever testes, testar scheduling, validar KPIs,
  testar alarmes, invariantes ISOP, property-based testing.
---

# Testes de Domínio PP1

## ISOP Parsing
- Coluna F NUNCA usada como deadline
- Coluna K NUNCA usada como stock
- Stock real = valores positivos nas datas
- Negativos = encomendas INDEPENDENTES (não cumulativas)
- |negativo| = quantidade a produzir
- Data coluna = deadline

## Peças Gémeas
- Quantidade = max(|A|, |B|) para ambas
- Tempo = uma quantidade (não dobro)
- Excedente → stock

## Scheduling Core
- Nenhuma máquina com 2 operações simultâneas
- Lote económico NUNCA atrasa encomenda
- PRM020 NUNCA no plano
- Turno noite só quando 2 turnos insuficientes
- ATCS: prioridade > 0 para todos os jobs
- Operação dentro zona frozen requer approvalFlag
- freezeStatus ∈ {'frozen', 'slushy', 'liquid'}

## Configuração
- Zod schema valida toda config antes de usar
- Weights somam <= 1.0 (ou normalizar)
- dispatchRule é um dos valores do enum
- Política "Modo Urgente" → otd weight = 1.0

## Prioridade
- Encomenda atrasada > lote económico
- Encomenda atrasada > agrupamento setups
- 2 turnos insuficientes → sinalizar turno noite

## Padrão
- describe('Invariante: [nome]')
- Boundary conditions (0, max, overflow)
- Property-based: fast-check para fórmulas ATCS
- Snapshot: componentes visuais alarme
