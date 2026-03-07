# Frontend PP1

React 18 + TypeScript strict + Vite + Zustand + Ant Design 5

## Regras estritas

- Componentes max 300 linhas. Hooks max 150 linhas.
- Nunca importar de dentro de outra feature (só index.ts)
- Zustand: selectores atómicos, nunca store inteiro
- Cores: NUNCA hardcodar — usar tokens/CSS variables
- Design ISA-101: fundo cinzento, cor só para anomalias
- Regra dos 3 Segundos: KPIs legíveis a 3m em 3s
- Tabelas: Ant Design Table. Gráficos: Apache ECharts
- Listas longas: TanStack Virtual
- Scheduling pesado: Web Worker (nunca main thread)
