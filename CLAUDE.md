# ProdPlan PP1 — Sistema APS de Planeamento de Produção Industrial

SaaS de planeamento e escalonamento de produção para fábricas de estampagem.
Fábrica actual: Incompol (5 prensas activas, 59 ferramentas, ~94 SKUs, 14 clientes).
Empresa: NIKUFRA.AI (Portugal).

## Arquitectura

Monorepo Turborepo + pnpm:
- `apps/frontend` — React 18 + TypeScript + Vite + Zustand (UI)
- `apps/backend` — FastAPI + PostgreSQL (persistência, sem solver)
- `packages/scheduling-engine` — TypeScript puro (scheduling 100% client-side)

## Comandos

pnpm dev | pnpm build | pnpm test | pnpm lint | pnpm format

## Convenções

- Named exports (nunca default). Ficheiros max 400 linhas.
- Zustand: selectores atómicos, nunca raw store.
- Biome formata TS. Ruff formata Python.

## ════ PRIORIDADE Nº1 DO SISTEMA ════

**ENTREGAR TUDO A TEMPO. Sem excepção.**
Todas as decisões — sequenciação, alocação, setups, lote económico —
são SUBORDINADAS a este objectivo.

## ════ DADOS ISOP ════

### Colunas

| Col | Campo | USAR? |
|-----|-------|-------|
| A | Cliente | SIM |
| B | Nome | SIM |
| C | Ref. Artigo (SKU) | SIM |
| D | Designação | SIM |
| E | Lote Económico | SOFT — só se houver tempo livre |
| F | Prz.Fabrico | **IGNORAR SEMPRE** |
| G | Máquina | SIM |
| H | Ferramenta | SIM |
| I | Peças/H (cadência) | SIM |
| J | Nº Pessoas | SIM |
| K | STOCK-A | **IGNORAR SEMPRE** |
| L | WIP | SIM |
| M | Peça Gémea | SIM |
| N | ATRASO | SIM |
| O+ | Datas (~80 dias) | SIM — FONTE PRINCIPAL |

### Valores NP nas datas

- **Positivo** (preto) = STOCK REAL disponível nesse dia
- **Negativo** (vermelho) = ENCOMENDA INDEPENDENTE
  - |valor| = quantidade a produzir
  - Data da coluna = DEADLINE
  - Cada negativo é SEPARADO, NÃO cumulativo
  - -9600 no dia 10 NÃO inclui -2853 do dia 5
- **Vazio** = sem dados

### Colunas IGNORADAS

- F (Prz.Fabrico): deadlines vêm dos negativos, não daqui
- K (STOCK-A): stock real = valores positivos nas datas

### Lote Económico — SOFT

Se houver tempo após agendar TUDO a tempo → produzir lote económico.
Se NÃO houver tempo → IGNORAR. NUNCA atrasa encomenda.

### Stock real

= último valor POSITIVO antes do primeiro negativo nas datas.

## ════ PEÇAS GÉMEAS ════

Pares LH/RH, mesma ferramenta, mesma máquina, produção SIMULTÂNEA.
Quantidade = max(|NP_A|, |NP_B|) para AMBAS.
Tempo = tempo de UMA quantidade (não o dobro).
Excedente → stock.

## ════ MÁQUINAS ════

| Máq | Área | SKUs | Notas |
|-----|------|------|-------|
| PRM019 | Grandes | 21 | — |
| PRM031 | Grandes | 20 | Alta carga FAURECIA |
| PRM039 | Grandes | 28 | Maior variedade |
| PRM042 | Médias | 11 | **SEM ALTERNATIVA** |
| PRM043 | Grandes | 14 | — |

**PRM020 — FORA DE USO. IGNORAR.**

## ════ TURNOS ════

Prensas Grandes (019/031/039/043):
- A: 07:00–15:30 → 6 pessoas (5 + 1 geral)
- B: 15:30–00:00 → 5 pessoas

Prensa Média (042):
- A: 07:00–15:30 → 9 pessoas (5 + 4 geral)
- B: 15:30–00:00 → 4 pessoas

Turno Noite (00:00–07:00): SÓ EM EMERGÊNCIA.
Criado quando impossível entregar a tempo com 2 turnos.

Normal: 1020 min/dia | Emergência: 1440 min/dia

## ════ 4 CONSTRAINTS ════

1. SetupCrew: máx 1 setup simultâneo na fábrica
2. ToolTimeline: ferramenta em 1 máquina de cada vez
3. CalcoTimeline: calço em 1 máquina de cada vez
4. OperatorPool: capacidade operadores por turno/área (advisory)

## ════ MOTOR DE SCHEDULING ════

### Arquitectura de 3 camadas

Camada 1 — ATCS (instantâneo, <10ms):
Regra de despacho com 3 termos exponenciais.
Prioridade(j) = (w/p) × exp(-slack/k1p̄) × exp(-setup/k2s̄)

Camada 2 — Busca local (1-3 seg, Web Worker):
SA ou Tabu Search refinam a solução ATCS. 5-15% melhoria.

Camada 3 — CP solver (futuro, WASM):
MiniZinc-js com Gecode/Chuffed para otimização pesada.

### Configuração pelo utilizador

- Sliders de peso: OTD vs Setups vs Utilização
- Políticas: "Maximizar OTD" | "Minimizar Setups" | "Equilibrado"
- Regras custom via expr-eval (fórmulas) e json-rules-engine
- Strategy Pattern: SchedulingStrategy.score(job, machine, ctx)
- Config persistida em JSON validado com Zod

### Replaneamento por camadas

1. Right-shift (< 30 min perturbação)
2. Match-up (30 min – 2h)
3. Parcial (> 2h, só operações afetadas)
4. Regeneração total (catástrofe)
+ Turno noite automático quando 2 turnos não bastam

### Zonas de horizonte

- CONGELADO (0–5 dias): sem alterações sem aprovação
- SEMIFLEXÍVEL (5 dias–2 sem): alterações negociadas
- LÍQUIDO (resto): alterações livres

## Docs detalhados

- docs/agent/scheduling-engine.md
- docs/agent/factory-data.md
- docs/agent/design-system.md
- docs/agent/algorithms.md
