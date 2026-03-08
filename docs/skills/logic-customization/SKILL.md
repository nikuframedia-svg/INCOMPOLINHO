---
name: prodplan-logic-customization
description: |
  Implementa customização de lógica pelo utilizador.
  Usar para: regras SE/ENTÃO, fórmulas custom, definições de conceito,
  workflows, estratégias multi-passo, governance levels.
---

# Customização de Lógica PP1

## 7 Níveis (L1 mais simples → L7 mais profundo)

### L1: Parâmetros (sliders Zustand → SchedulingConfig)
### L2: Regras SE/ENTÃO (react-querybuilder → json-rules-engine)
  - Exportar para JSON. Avaliar no motor. Sem eval().
### L3: Fórmulas (expr-eval)
  - Parser seguro baseado em AST. Variáveis injectadas pelo sistema.
  - Autocomplete de variáveis no UI.
### L4: Definições de conceito (DoctrineConfig Zod schema)
  - "atrasado", "urgente", "robusto" = fórmulas custom por fábrica
### L5: Workflows (GovernanceConfig Zod schema)
  - Quem aprova o quê. Governance level por acção. SoD.
### L6: Estratégias multi-passo (StrategyConfig Zod schema)
  - Lista ordenada de passos. Cada passo: filtro + regra + pesos.
### L7: Plugins Python (Fase 2+)

## Princípio: Preview Antes de Aplicar
TODA alteração de lógica deve ter preview:
"Com esta regra, X operações seriam classificadas como urgentes"
"Esta estratégia produz OTD 96.2% vs 97.1% da actual"
NUNCA aplicar sem preview. NUNCA.

## Princípio: Tudo Versionado
Cada alteração cria nova versão. Rollback para qualquer versão anterior.
