---
name: prodplan-user-configuration
description: |
  Implementa configuração de scheduling pelo utilizador.
  Usar para: sliders, políticas, regras custom, fórmulas,
  presets, cenários what-if, decision tables.
---

# Configuração pelo Utilizador PP1

## Arquitectura de 4 camadas

### Camada 1: Config JSON + Zod
Schema TypeScript com Zod para validação runtime.
Versionamento semântico com funções de migração.
```typescript
const SchedulingConfigSchema = z.object({
  version: z.literal(1),
  weights: z.object({
    otd: z.number().min(0).max(1).default(0.7),
    setupMinimization: z.number().min(0).max(1).default(0.2),
    utilization: z.number().min(0).max(1).default(0.1),
  }),
  dispatchRule: z.enum(['ATCS', 'EDD', 'CR', 'SPT', 'WSPT']).default('ATCS'),
  direction: z.enum(['forward', 'backward', 'auto']).default('auto'),
  frozenHorizonDays: z.number().min(0).max(14).default(5),
  lotEconomicoMode: z.enum(['ignore', 'soft', 'fill']).default('soft'),
  emergencyNightShift: z.boolean().default(false),
  constraints: z.object({
    setupCrew: z.object({ enabled: z.boolean().default(true), maxSimultaneous: z.number().default(1) }),
    toolTimeline: z.object({ enabled: z.boolean().default(true) }),
    calcoTimeline: z.object({ enabled: z.boolean().default(true) }),
    operatorPool: z.object({ enabled: z.boolean().default(true), mode: z.enum(['hard', 'advisory']).default('advisory') }),
  }),
});
```

### Camada 2: Strategy Pattern
Interface SchedulingStrategy com método score(job, machine, context): number
Implementações: MaxOTDStrategy, MinSetupsStrategy, WeightedCompositeStrategy
Troca de estratégia via config JSON, sem recompilação.

### Camada 3: Fórmulas custom (expr-eval)
Utilizador escreve: otdWeight * (1/slack) + setupWeight * setupPenalty
Variáveis conhecidas injectadas no contexto.
Validação no parse-time. Sem eval(), baseado em AST.

### Camada 4: Regras visuais (react-querybuilder)
SE slack < 24h E setup ≠ actual ENTÃO boost prioridade +10
Exporta para JSON. Avaliado por json-rules-engine.

## Políticas pré-definidas
- "Maximizar OTD": weights {otd: 0.9, setup: 0.05, util: 0.05}
- "Minimizar Setups": weights {otd: 0.5, setup: 0.4, util: 0.1}
- "Equilibrado": weights {otd: 0.7, setup: 0.2, util: 0.1}
- "Modo Urgente": weights {otd: 1.0, setup: 0, util: 0}
- "Personalizado": sliders livres

## Cenários What-If
1. Baseline (escalonamento actual)
2. Clonar para sandbox
3. Modificar parâmetros/pesos
4. Reexecutar (<3 seg)
5. Comparar KPIs lado a lado
6. Confirmar ou descartar

## Sliders UI
- Debounce 300ms antes de reescalonar
- Split-pane: Gantt actual vs preview
- Indicadores: "Altera 15 jobs, OTD +2%, setups -18%"
