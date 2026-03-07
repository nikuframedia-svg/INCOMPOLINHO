# Design System Industrial PP1

## 1. Paleta ISA-101 Completa

### Backgrounds — Hierarquia de 4 Níveis

| Nível | Variável | Hex | Uso |
|-------|----------|-----|-----|
| 0 | `--bg-void` | #060810 | Fundo da página |
| 1 | `--bg-base` | #0c1017 | TopBar, superfície base |
| 2 | `--bg-card` | #12171f | Cards, painéis, secções |
| 3 | `--bg-raised` | #1a2029 | Inputs, dropdowns, table headers |

Regra: cada nível de profundidade sobe exactamente 1 nível.

### Borders

| Variável | Valor | Uso |
|----------|-------|-----|
| `--border-subtle` | rgba(255,255,255,0.06) | Separadores entre cards |
| `--border-default` | rgba(255,255,255,0.09) | Borders de inputs |
| `--border-hover` | rgba(255,255,255,0.14) | Hover em cards/inputs |
| `--border-active` | rgba(20,184,166,0.40) | Focus/active state |

NUNCA usar borders sólidas. SEMPRE rgba com alpha baixo.

### Texto — 4 Níveis de Contraste

| Variável | Hex | Weight | Uso |
|----------|-----|--------|-----|
| `--text-primary` | #e8ecf2 | 600 | Valores, headings |
| `--text-secondary` | #8899aa | 400 | Labels, descrições |
| `--text-muted` | #556677 | 400 | Timestamps, info terciária |
| `--text-ghost` | #334455 | 400 | Disabled, placeholders |

Branco puro (#ffffff) PROIBIDO em texto corrido. Excepção: botão primary.

### Accent — Teal (Cor Única)

| Variável | Valor | Uso |
|----------|-------|-----|
| `--accent` | #14b8a6 | Links, estados activos |
| `--accent-hover` | #0d9488 | Hover em accent |
| `--accent-bg` | rgba(20,184,166,0.10) | Fundo de badges |
| `--accent-border` | rgba(20,184,166,0.25) | Border selecionados |
| `--accent-light` | #2dd4bf | Gradientes em barras |

### Cores Semânticas (SÓ para estados de dados)

| Estado | Variável | Hex | Background |
|--------|----------|-----|------------|
| Positivo/Sucesso | `--semantic-green` | #10b981 | rgba(16,185,129,0.12) |
| Negativo/Erro | `--semantic-red` | #ef4444 | rgba(239,68,68,0.12) |
| Aviso/Pendente | `--semantic-amber` | #f59e0b | rgba(245,158,11,0.12) |
| Informação | `--semantic-blue` | #3b82f6 | rgba(59,130,246,0.12) |

NUNCA usar cores semânticas para decoração. SÓ para dados/estados.

## 2. Estados de Alarme ISA-18.2 (7 Estados)

| Estado | Condição | Visualização | Acção |
|--------|----------|--------------|-------|
| **Normal** | Sem alarme | Sem indicação visual | — |
| **Unacknowledged + Active** | Alarme novo, activo | **INTERMITENTE** (piscar) | Requer resposta do operador |
| **Acknowledged + Active** | Reconhecido, ainda activo | **SÓLIDO** (cor fixa) | Em tratamento |
| **Unacknowledged + Inactive** | Alarme retornou, não reconhecido | Intermitente suave | Reconhecer |
| **Acknowledged + Inactive** | Reconhecido, resolvido | Sem indicação (limpo) | Automático |
| **Shelved** | Temporariamente suprimido | Ícone "pause" discreto | Rever no tempo limite |
| **Out of Service** | Desactivado intencionalmente | Ícone "disabled" | — |

### Prioridades de Alarme (máx 4)

| Prioridade | Cor | Hex | Critério | Limite |
|------------|-----|-----|----------|--------|
| **CRITICAL** | Vermelho | #FF0000 | Perigo imediato, perda de produção | Max 1-2% do total |
| **HIGH** | Laranja | #FF8C00 | Acção urgente necessária | Max 5% do total |
| **MEDIUM** | Amarelo | #FFD700 | Atenção necessária em breve | — |
| **LOW** | Azul claro | #00BFFF | Informativo, sem urgência | — |

Regras:
- Max 4 prioridades (NUNCA mais)
- Max 5% dos alarmes como HIGH
- Todo alarme REQUER resposta definida do operador
- NUNCA só cor — SEMPRE cor + forma + texto

## 3. KPIs EEMUA 191

### Métricas de Performance de Alarmes

| KPI | Target | Cálculo |
|-----|--------|---------|
| Alarmes / 10 min | < 1 (ideal) | Média de alarmes activados por janela de 10 min |
| Standing alarms | < 10 | Alarmes activos há mais de 24h sem resolução |
| Chattering | 0 | Alarmes que activam/desactivam >3x em 60 seg |
| % acknowledged < 10 min | > 95% | Tempo até reconhecimento |
| Stale alarms | 0 | Alarmes activos há mais de 7 dias |

### Badge de Saúde do Sistema de Alarmes

| Estado | Cor | Condição |
|--------|-----|----------|
| Excelente | Verde #2D862D | <1 alarme/10min, 0 standing |
| Aceitável | Amarelo #FFD700 | 1-2 alarmes/10min, <5 standing |
| Sobrecarga | Vermelho #FF0000 | >2 alarmes/10min ou >10 standing |

## 4. Tipografia

### Fontes

| Uso | Fonte | Fallback |
|-----|-------|----------|
| Body text, labels, headings | **Inter** | system-ui, sans-serif |
| Códigos, SKUs, IDs, hashes, valores técnicos | **JetBrains Mono** | ui-monospace, monospace |

### Tamanhos

| Elemento | Tamanho | Weight | Variável |
|----------|---------|--------|----------|
| KPI grande (dashboard) | 32px | 700 | `--font-size-kpi` |
| Heading de card | 14px | 600 | `--font-size-heading` |
| Body text | 13px | 400 | `--font-size-body` |
| Label/caption | 11px | 400 | `--font-size-caption` |
| Badge/tag | 10px | 600 | `--font-size-badge` |
| Código técnico (mono) | 12px | 400 | `--font-size-mono` |

Mínimo absoluto: **10px**. Abaixo disso é ilegível.

### Regra dos 3 Segundos
KPIs no dashboard devem ser legíveis a 3 metros de distância em 3 segundos.
Implica: fonte grande (32px+), contraste alto, sem clutter visual.

## 5. Hierarquia de Ecrãs (L1-L4)

### L1 — Dashboard KPIs (Vista Geral)
- **Objectivo**: Estado da fábrica num relance
- **Componentes obrigatórios**:
  - 6 KPI cards (OTD, utilização, setups, backlog, cobertura, operadores)
  - Heatmap de carga por máquina × dia
  - Indicadores de alarme (badge com contagem)
- **Interacção**: Click em KPI → navega para L2/L3 relevante

### L2 — Vista de Recursos (Gantt, Fábrica)
- **Objectivo**: Planeamento e monitorização por recurso
- **Componentes obrigatórios**:
  - Gantt chart (máquinas × tempo)
  - Histograma de capacidade por máquina
  - Timeline de turnos (A/B/Noite)
  - Lista de operações com filtros
- **Interacção**: Click em bloco Gantt → abre L3 do SKU/encomenda

### L3 — Detalhe (Peça, Encomenda, Máquina)
- **Objectivo**: Toda a informação sobre uma entidade
- **Componentes obrigatórios**:
  - Header com ID, nome, estado
  - Timeline de produção (passado + planeado)
  - Tabela de encomendas/operações
  - Métricas específicas (cobertura, OTD individual)
- **Interacção**: Edição directa (drag-drop no Gantt), links para entidades relacionadas

### L4 — Configuração (Definições)
- **Objectivo**: Parametrização do sistema
- **Componentes obrigatórios**:
  - Formulários com validação inline
  - Preview de impacto (antes/depois)
  - Confirmação explícita de alterações
- **Interacção**: Sliders, toggles, selects, formulários

## 6. Componentes Obrigatórios por Ecrã

### Dashboard (L1)
- `KPICard` × 6 com PulseStrip (indicador de tendência)
- `HeatmapGrid` (máquinas × dias, cores por utilização)
- `AlarmBadge` (contagem por prioridade)
- `OperatorAllocation` (PG1/PG2 por turno)
- `BacklogTable` (SKUs com atraso)

### Fábrica (L2)
- `MachineCard` × 5 (uma por prensa activa)
- `SparklineChart` (mini gráfico de utilização)
- `HeatmapRow` (carga por dia)
- `OperatorDemand` (necessidade vs disponível)

### Planning/Gantt (L2)
- `GanttChart` (barras por máquina × tempo)
- `CapacityHistogram` (barra empilhada abaixo do Gantt)
- `ShiftOverlay` (faixas A/B/Noite no background)
- `ConstraintViolation` (indicadores inline)
- `DragHandle` (para resequenciação manual)

### Peças (L3)
- `SKUTable` (tabela com sorting, filtering, pagination)
- `CoverageBadge` (% cobertura com cor semântica)
- `MiniGantt` (timeline compacta por SKU)

### Definições (L4)
- `FileUpload` (ISOP XLSX)
- `DataPreview` (tabela de preview antes de aplicar)
- `SettingsForm` (OEE, turnos, dispatch rules)

## 7. Cores Gantt

| Estado | Hex | Uso |
|--------|-----|-----|
| On-time | #2D862D | Operação dentro do prazo |
| Late | #FF0000 | Operação atrasada (conclusão > deadline) |
| At-risk | #FFD700 | Operação com folga < 4h |
| Setup | #4169E1 | Bloco de setup (troca de ferramenta) |
| Idle | #D0D0D0 | Tempo ocioso |
| Infeasible | #808080 | Operação impossível de agendar |

## 8. Princípios ISA-101 Invioláveis

1. **Fundo neutro**: cinzento escuro (#060810 a #1a2029). Cor SÓ para anomalias
2. **2D simples**: ZERO 3D, sombras decorativas, gradientes decorativos
3. **Animação**: SÓ para alarmes não reconhecidos (intermitente). Nada mais.
4. **Texto**: Inter, mínimo 14px para informação operacional
5. **Cor + Forma + Texto**: NUNCA comunicar só com cor (acessibilidade)
6. **Densidade alta**: máximo de dados úteis no mínimo de espaço
7. **Hierarquia por contraste**: peso da fonte (400 vs 600) e opacidade, não tamanho
