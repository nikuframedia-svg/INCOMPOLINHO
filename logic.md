# PP1 Scheduler — Lógica Completa

Referência definitiva para reimplementação do scheduler Incompol.
Fábrica: Incompol (5 prensas, 59 ferramentas, ~94 SKUs, 14 clientes).

---

## 1. DADOS ISOP (Input)

### 1.1 Formato Excel

Ficheiro `.xlsx` com header dinâmico (procura "Cliente" na coluna A, linhas 1-20).

**Colunas mapeadas:**

| Header Excel | Campo interno | Uso |
|---|---|---|
| Cliente | client_id | "210020" |
| Nome | client_name | "FAURECIA" |
| Referência Artigo | sku | "1064169X100" |
| Designação | designation | texto livre |
| Lote Económico | eco_lot | HARD: mínimo de produção |
| Máquina | machine_id | "PRM031" |
| Ferramenta | tool_id | "BFP079" |
| Peças/H | pieces_per_hour (pH) | taxa produção |
| Nº Pessoas / Pessoas | operators | operadores necessários |
| WIP | wip | work-in-progress |
| ATRASO | backlog | quantidade em atraso |
| Peça Gémea | twin_ref | SKU da gémea (se existir) |
| Máquina alternativa | alt_machine | alternativa (se existir) |
| Tp.Setup | setup_hours | tempo setup (se existir) |

**IGNORAR SEMPRE:** `Prz.Fabrico`, `STOCK-A`

**Colunas de datas:** Todas as colunas com `datetime` no header = dias úteis (~80 dias). Extraídas como strings ISO `"2026-03-05"`.

### 1.2 Interpretação NP (Net Position) — CRÍTICO

Cada célula nas colunas de datas contém um valor NP:

- **Positivo (preto):** Stock real disponível nessa data
- **Negativo (vermelho):** Encomenda independente. `|valor|` = quantidade a produzir. Data da coluna = deadline
- **Vazio/Zero:** Sem dados

**Regras fundamentais:**
1. Cada célula NP negativa = 1 encomenda separada (valores repetidos CONTAM como encomendas distintas)
2. NP NÃO é cumulativo — é posição líquida
3. NUNCA deduplicar NP repetidos
4. NUNCA calcular deltas entre NP
5. NUNCA tratar NP como running total
6. Procura total = soma(|NP|) de TODAS células negativas

### 1.3 Extracção de Stock e Demand

```
Função: extract_stock_and_demand(np_values) → (stock, demand[])

stock = último valor positivo ANTES do primeiro negativo
demand[dia] = |NP| se NP < 0, senão 0

Exemplo: np_values = [2751, 2751, 2751, -15600, 0, -10400]
  → stock = 2751 (último positivo antes do -15600)
  → demand = [0, 0, 0, 15600, 0, 10400]
```

**Nota:** O primeiro NP negativo JÁ tem o stock deduzido internamente. Por isso `surplus` começa a 0 no lot sizing (não se re-deduz stock).

### 1.4 Filtros de Input

- **PRM020** — fora do âmbito; operações nesta máquina fazem falhar a importação
  com diagnóstico explícito, sem descartar procura
- **pH <= 0** — Warning, default para 1.0
- **SKU vazio** — Para leitura (break)
- Valores safe: `_safe_int(None) = 0`, `_safe_int("") = 0`, `_safe_int("abc") = 0`

### 1.5 RawRow (estrutura de output do parser)

```
RawRow:
  client_id: str          # "210020"
  client_name: str        # "FAURECIA"
  sku: str                # "1064169X100"
  designation: str
  eco_lot: int            # HARD (0 = sem eco lot)
  machine_id: str         # "PRM031"
  tool_id: str            # "BFP079"
  pieces_per_hour: float  # 1681.0
  operators: int          # 1
  wip: int
  backlog: int
  twin_ref: str           # SKU da gémea (vazio se não há)
  np_values: list[int]    # positivo=stock, negativo=encomenda, 0=vazio
```

---

## 2. TRANSFORMAÇÃO (RawRow → EngineData)

### 2.1 Pipeline

```
RawRows
  ↓ extract_client_demands()     — preserva por-cliente ANTES do merge
  ↓ _raw_to_eop() × N           — cada RawRow → EOp (enriquece com YAML)
  ↓ merge_multi_client()         — agrupa por (sku, machine, tool)
  ↓ identify_twins()             — detecta pares gémeos
  ↓ _build_machines()            — lista de máquinas
  ↓ _resolve_holidays()          — feriados → índices de workday
→ EngineData
```

### 2.2 Enrichment com Master Data (YAML)

O `_raw_to_eop()` enriquece cada RawRow com dados do `factory.yaml`:

- **Setup hours:** `setup_hours[tool_id]` ou `_default: 0.5h`
- **Alt machine:** `alt_machines[tool_id].alt` ou None
- **OEE:** `factory.oee_default` = 0.66
- **ID:** formato `"{tool}_{machine}_{sku}"`
- **pH:** se `raw.pH <= 0` → default 1.0
- **operators:** se `raw.operators <= 0` → default 1

O ISOP define as referências e ferramentas ativas. A configuração pode manter
referências históricas sem linha no ISOP atual para preservar regras de
planeamento e subcontratação; `CF589MMA1A02.20` é um caso operacional que deve
continuar visível como origem `config` quando não existe no upload.

### 2.3 Multi-Client Merge

Operações com mesmo `(sku, machine_id, tool_id)` de clientes diferentes são fundidas:

| Campo | Regra |
|---|---|
| d (demand) | SOMA por dia |
| client | join sorted unique names |
| pH | MIN (conservativo) |
| operators | MAX |
| eco_lot | MAX |
| stk | MAX |
| backlog | SOMA |
| wip | MAX |
| Outros | do primeiro op (base) |

Resultado: ~94 linhas ISOP → ~59 ops após merge.

### 2.4 Detecção de Twins (Peças Gémeas)

**3 estratégias por prioridade:**

1. **YAML (preferida):** `twins: { "BFP079": ["SKU_A", "SKU_B"] }` — procura ops por (sku, tool_id). Se um SKU está no ISOP e outro não → warning.

2. **Coluna ISOP:** `twin_ref` mapping `{op_id → twin_sku}`. Procura por (sku, machine, tool). Marca pares como `seen` para evitar duplicação.

3. **Auto-detect:** Agrupa ops por (tool, machine).
   - 2 SKUs distintos = par gémeo ✓
   - 3+ SKUs = AMBÍGUO → warning, nenhum twin criado
   - 1 SKU = não é twin

**TwinGroup:**
```
TwinGroup:
  tool_id: str       # ferramenta partilhada
  machine_id: str    # máquina partilhada
  op_id_1, op_id_2   # IDs das duas operações
  sku_1, sku_2        # SKUs
  eco_lot_1, eco_lot_2
```

### 2.5 Holidays (Feriados)

Duas fontes combinadas:
1. **Auto-detect weekends:** `date.weekday() >= 5` (Sábado/Domingo)
2. **YAML explícito:** `holidays: ["2026-01-01", "2026-04-25", ...]`

Convertidos para índices de workday (0-based).

### 2.6 Client Demands (pré-merge)

Preservado ANTES do merge para vista de expedição:
```
ClientDemandEntry:
  client, sku, day_idx, date
  order_qty: abs(NP)      # encomenda real
  np_value: NP original   # negativo
```
Dict keyed por SKU.

### 2.7 EOp (Engine Operation)

```
EOp:
  id: str              # "{tool}_{machine}_{sku}"
  sku, client, designation
  m: str               # machine_id
  t: str               # tool_id
  pH: float            # peças/hora (min 1.0)
  sH: float            # setup hours (do YAML, default 0.5)
  operators: int
  eco_lot: int          # HARD (0 = sem)
  alt: str | None       # máquina alternativa
  stk: int              # stock real (do NP)
  backlog: int
  d: list[int]          # demand/dia: |NP neg|, 0 nos outros
  oee: float            # 0.66
  wip: int
```

### 2.8 EngineData (contrato completo)

```
EngineData:
  ops: list[EOp]                    # ~59 operações
  machines: list[MachineInfo]       # 5 máquinas activas
  twin_groups: list[TwinGroup]      # pares gémeos
  client_demands: dict[sku → list[ClientDemandEntry]]
  workdays: list[str]               # ["2026-03-05", ...]
  n_days: int                       # ~80 dias úteis
  holidays: list[int]               # índices de dias não-úteis
  machine_blocked_days: dict[str, set[int]]  # por máquina (simulação)
  tool_blocked_days: dict[str, set[int]]     # por ferramenta (simulação)

MachineInfo:
  id: str        # "PRM019"
  group: str     # "Grandes" ou "Medias"
  day_capacity: int  # 1020
```

---

## 3. GUARDIAN (Validação Input/Output)

### 3.1 Input Validation (pré-schedule)

| Campo | Severidade | Acção |
|---|---|---|
| op.id duplicado | drop | remove operação |
| pH <= 0 | drop | remove operação |
| machine não existe | drop | remove operação |
| eco_lot < 0 | fix | eco_lot = 0 |
| len(d) != n_days | fix | pad/truncate |
| oee <= 0 ou > 1.0 | fix | oee = 0.66 |
| sH < 0 | fix | sH = 0 |
| demand=0 + backlog=0 | warn | sem acção |
| twin ref op inexistente | drop twin | remove TwinGroup |
| twin máquinas diferentes | warn | mantém |

Retorna `GuardianResult(cleaned, dropped_ops, issues, is_clean)`.

### 3.2 Output Validation (pós-schedule)

- Segmento fora do horizonte (`day_idx >= n_days`)
- Segmento fora dos turnos (`start_min < 420` ou `end_min > 1440`)
- Máquina órfã (não existe em EngineData)
- Quantidade negativa (`qty < 0`)
- **Overlap detection:** segmentos no mesmo (machine, day) com sobreposição temporal

---

## 4. SCHEDULER — 5 FASES

### Pipeline completo:

```
EngineData
  ↓ Guardian (validate_input)
  ↓ Phase 1: Lot Sizing        — EOps → Lots
  ↓ Phase 2: Tool Grouping     — Lots → ToolRuns
  ↓ Phase 3: Dispatch           — Assign + Sequence + Allocate → Segments
  ↓ Auto Buffer (se necessário)
  ↓ Phase 4: Material/Prazo     — Release-first + prazo de produção
  ↓ Phase 4b: VNS               — Polish (swap, relocate, cross-machine)
  ↓ Unshift Buffer
  ↓ Fix Overlaps + Crew Serialization + Sanitize
  ↓ Phase 5: Scoring            — OTD, OTD-D, earliness, setups, utilisation
  ↓ Operator Alerts
  ↓ Guardian (validate_output)
→ ScheduleResult
```

---

## 5. PHASE 1: LOT SIZING

**Input:** EngineData → **Output:** list[Lot]

### 5.1 Solo Lots (operações não-twin)

```
surplus = 0   # NÃO se re-deduz stock (primeiro NP neg já tem stock deduzido)

Para cada dia com demand > 0:
  Se surplus >= demand:
    surplus -= demand
    → nenhum lote criado
  Senão:
    deficit = demand - surplus
    qty = eco_lot_hard(deficit, eco_lot)   # ceil(deficit/eco_lot) × eco_lot
    surplus = qty - deficit
    prod_min = max(MIN_PROD_MIN, (qty / (pH × OEE)) × 60)
    setup_min = sH × 60
    → Criar Lot(qty, prod_min, setup_min, edd=day_idx)
```

### 5.2 Eco Lot HARD

```
Se eco_lot <= 0 ou demand <= 0: retorna demand
Senão: ceil(demand / eco_lot) × eco_lot    # SEMPRE arredonda para CIMA
```

### 5.3 Twin Lots (peças gémeas)

```
Validar eco_lot_effective_a == eco_lot_effective_b.
Se forem diferentes, bloquear o cálculo e exigir correção dos dados.

Criar eventos cronológicos de procura A e B e aplicar o excedente FIFO por SKU.
Para o evento mais urgente:
  procurar o evento oposto mais próximo até 5 dias de entrega

  Se existe parceiro:
    qty = max(eco_lot_hard(need_a), eco_lot_hard(need_b))
  Senão:
    qty = eco_lot_hard(need_urgente)

  Em ambos os casos:
    qty_a = qty_b = qty
    marcar como stock coproduzido o output sem procura compatível

  Debitar cada output na procura futura do respetivo SKU e transportar excedente.

  time_a = (qty_a / (pH_a × OEE)) × 60
  time_b = (qty_b / (pH_b × OEE)) × 60
  prod_min = max(MIN_PROD_MIN, max(time_a, time_b))  # UMA execução, NÃO soma

  twin_outputs = [(op_id_a, sku_a, qty_a), (op_id_b, sku_b, qty_b)]
```

**REGRA FUNDAMENTAL:** todo ciclo gémeo tem `qty_a == qty_b > 0` e o tempo máquina é `max(time_A, time_B)`, nunca a soma. O excedente intencional fica disponível para procuras futuras do mesmo SKU; não cria uma encomenda nem um envio SUBC fictícios.

### 5.4 Emparelhamento complementar

Não existe merge posterior de lotes. O emparelhamento é feito antes da criação,
independentemente da ordem A/B, e cada evento de procura só pode ser consumido
uma vez. O lote conjunto usa o prazo de produção mais cedo e a libertação de
material mais cedo, porque a matéria-prima da necessidade urgente alimenta os
dois outputs do ciclo. Sem procura oposta até cinco dias de entrega, o ciclo
continua fisicamente 1:1 e o output sem procura emparelhada é registado como
stock coproduzido.

### 5.5 Holiday Adjustment

EDDs que caem em feriados são recuados para o dia útil anterior:
```
Enquanto lot.edd está em holidays E lot.edd > 0:
  lot.edd -= 1
```

### 5.6 Lot (estrutura)

```
Lot:
  id: str                   # "LOT_{tool}_{machine}_{sku}_{day_idx}"
  op_id: str                # EOp.id de origem
  tool_id, machine_id
  alt_machine_id: str|None
  qty: int                  # peças (eco lot rounded)
  prod_min: float           # minutos de produção
  setup_min: float          # minutos de setup (do YAML)
  edd: int                  # deadline (day_idx, 0-based)
  is_twin: bool
  twin_outputs: [(op_id, sku, qty)] | None
```

---

## 6. PHASE 2: TOOL GROUPING

**Input:** list[Lot] → **Output:** list[ToolRun]

### 6.1 Agrupamento

Agrupar lotes por `(tool_id, machine_id)`. Dentro de cada grupo, ordenar SEMPRE por EDD (Fix 1).

### 6.2 Splitting (3 critérios)

O grupo é partido quando:

1. **EDD gap > MAX_EDD_GAP (10):** Gap entre EDDs consecutivos > 10 dias
2. **Duration > MAX_RUN_DAYS × DAY_CAP (5 × 1020 = 5100 min):** Produção acumulada excede 5 dias
3. **EDD span > MAX_EDD_SPAN (30):** Span do primeiro ao último lote > 30 dias

### 6.3 Infeasibility Split

Se `run.total_min > (edd + 1) × DAY_CAP` e run tem 2+ lots:
- Lotes early-EDD que cabem na capacidade → run `_early`
- Lotes restantes → run `_late`

### 6.4 ToolRun (estrutura)

```
ToolRun:
  id: str                    # "run_{tool}_{machine}_{idx}"
  tool_id, machine_id
  alt_machine_id: str|None
  lots: list[Lot]            # ordenados por prazo operacional
  setup_min: float           # UM setup para todo o grupo
  total_prod_min: float      # soma prod_min dos lotes
  total_min: float           # setup + prod
  edd: int                   # alias compatível de production_due_day
  production_due_day: int    # entrega normal ou envio subcontratado
  lst: int = 0               # Latest Start Time (preenchido na Phase 4)
```

---

## 7. PHASE 3: DISPATCH (Assign + Sequence + Allocate)

### 7.1 Assign Machines

**1º passo:** Runs SEM alt → vão para a máquina primária.

**2º passo:** Runs COM alt → load-balance:
- Se `run.edd ≤ 5` (urgente): compara early-load (soma de runs com edd ≤ run.edd) em cada máquina
- Se `run.edd > 5`: compara carga total
- Escolhe a máquina MENOS carregada
- Runs maiores processados primeiro (`sort by -total_min`)

### 7.2 Sequencing (por máquina)

Pipeline sequencial de 4 heurísticas:

**1. EDD baseline:** Sort por `run.edd`

**2. Campaign (nearest-neighbor):**
```
result = [runs[0]]
Para cada posição seguinte:
  candidates = runs com edd ≤ last.edd + campaign_window (15)
  Se há runs com mesmo tool_id → escolhe o de menor EDD
  Senão → escolhe o de menor EDD
```

**3. Interleave Urgent (Fix 4):**
```
Se dois runs consecutivos têm o mesmo tool_id (campanha):
  Procura mais à frente um run com tool diferente E edd < next_run.edd
  Se encontra → insere-o entre os dois, quebrando a campanha
  Custo: +2 setups. Benefício: run urgente não fica bloqueado.

Exemplo: [T1 edd=4, T1 edd=11, T2 edd=6] → [T1 edd=4, T2 edd=6, T1 edd=11]
```

**4. 2-Opt Local:**
```
Para cada par de runs adjacentes com tools diferentes:
  Procura até 4 posições à frente um run com o mesmo tool_id
  Se |edd_difference| ≤ EDD_SWAP_TOLERANCE (5): swap
  → Estende a campanha, -1 setup
```

### 7.3 Segment Allocation (per-machine dispatch)

**Estruturas de estado:**
- `MachineState`: `available_at`, `last_tool`, `used_per_day`
- `CrewState`: `available_at` (single setup crew)
- `ToolTimeline`: bookings por tool (previne tool em 2 máquinas ao mesmo tempo)

**Algoritmo:**

```
Priority queue: (available_at, edd, machine_id)

Enquanto há runs na fila:
  Pop máquina com menor available_at (desempata por EDD mais urgente)

  Para cada run na queue dessa máquina:
    Se há LST gate → snap available_at para o gate

    needs_setup = (last_tool != run.tool_id)

    Tool contention: espera se tool está booked noutra máquina
    Setup: wait for crew, advance crew.available_at

    Para cada lot (em ordem EDD):
      remaining_min = lot.prod_min
      remaining_qty = lot.qty

      Enquanto remaining > 0:
        Snap to shift (skip holidays)
        day_remaining = SHIFT_B_END - min_in_day

        Se setup não cabe no dia → próximo dia
        prod_available = day_remaining - seg_setup
        block_min = min(remaining, prod_available)
        block_qty = proportional (block_min / lot.prod_min × lot.qty)

        Criar Segment(day_idx, start_min, end_min, shift, qty, prod_min, setup_min)

        Twin outputs: proporcionais ao block_qty

    Se próximo run tem o mesmo tool → campaign continuation (skip heap)
    Senão → break, re-enqueue no heap
```

### 7.4 Segment (estrutura)

```
Segment:
  lot_id, run_id, machine_id, tool_id
  day_idx: int              # dia útil (0-based, pode ser negativo se buffer)
  start_min: int            # minuto no dia (420-1440, clock from midnight)
  end_min: int
  shift: str                # "A" ou "B"
  qty: int                  # peças produzidas
  prod_min: float           # tempo de produção
  setup_min: float          # > 0 APENAS no 1º segment do ToolRun
  is_continuation: bool     # True se não é 1º segment do lot
  edd: int                  # deadline
  sku: str
  twin_outputs: [(op_id, sku, qty)] | None
```

---

## 8. AUTO BUFFER

Antes do dispatch, detecta infeasibilidade per-machine:

```
Para cada máquina, simula dispatch por prazo de produção:
  Se qualquer run completa depois do seu prazo:
    buffer_days = max(tardiness observada)

Se buffer_days > 0:
  Todos os marcos (entrega, envio, prazo, referência e libertação) += buffer_days
  Os marcos por output de lotes gémeos também += buffer_days
  EngineData.n_days += buffer_days
  Holidays shift += buffer_days
  Re-assign machines

Após JIT, unshift:
  Segmentos: day_idx -= buffer_days (pode ficar negativo)
  Lots/Segmentos: todos os marcos -= buffer_days
```

---

## 9. PHASE 4: JIT (Just-In-Time)

**Objectivo:** Nunca produzir antes da libertação simulada de material e
concluir até ao último marco controlável pela fábrica.

### 9.1 Contrato de datas

Para cada necessidade:

- `customer_delivery_day` (`C`): compromisso do ISOP.
- `latest_subcontract_dispatch_day` (`H`): `C` menos o lead time útil do
  fornecedor.
- `subcontract_dispatch_day` (`P`): `H` menos o buffer de subcontratação.
- `production_due_day` (`U`): `P` para subcontratados; entrega ao cliente para
  artigos normais.
- `internal_target_day` (`I`): `U` menos o buffer interno de fim.
- `material_reference_day` (`M`): `P` para subcontratados; `C` para normais.
- `material_release_day` (`R`): `M` menos 5 dias úteis.

Fins de semana e feriados são ignorados na aritmética útil. Marcos anteriores
ao início do horizonte mantêm índices negativos para revelar compromissos já
vencidos; apenas a execução física é limitada a `D0`.

Num lote gémeo, cada output conserva os seus marcos isolados. Como os outputs
partilham a matéria-prima do mesmo ciclo, a janela conjunta usa
`R = min(R_output)` e `U = min(U_output)`: a libertação da necessidade mais
urgente autoriza o ciclo comum e a necessidade posterior pode ser coproduzida
antes da sua própria janela isolada.

### 9.2 Restrições e construção

1. Criar lotes e marcos por output.
2. Atribuir e ordenar por `production_due_day`, rutura e prioridade explícita.
3. Impor `productive_start >= R` e `productive_end <= U`.
4. Resolver globalmente máquina, ferramenta, setup e operadores.
5. Se a janela estrita for inviável, devolver `best_effort` sem relaxar `R`.
6. Normalizar o plano no primeiro intervalo legal sem piorar entregas ou envios.

O dispatch determinístico de fallback usa os mesmos limites. Os helpers
`LST`/backward permanecem apenas para compatibilidade e também usam `U`.

### 9.3 KPIs e gates

- OTD/OTD-D continuam referidos à entrega ao cliente. Para um output
  subcontratado, a disponibilidade ao cliente é a conclusão na fábrica mais o
  lead time útil do fornecedor.
- `subcontract_dispatch_misses` e
  `subcontract_dispatch_late_workdays` medem separadamente o handoff.
- Produção antes de `R` bloqueia aplicação; atraso de envio ou entrega exige
  aprovação explícita e permanece visível.

---

## 10. PHASE 4b: VNS (Variable Neighborhood Search)

**Objectivo:** Polish pós-JIT para reduzir setups e earliness.

### 10.1 Neighborhoods

**N1 — Swap Adjacent:**
- Troca runs adjacentes na mesma máquina
- Só se `|edd_diff| ≤ 2 × EDD_SWAP_TOLERANCE`
- Só se cria adjacência de tool (potencial -1 setup)

**N2 — Relocate:**
- Move run para junto de outro com o mesmo tool_id
- Mesma máquina, insert em posição adjacente
- Tolerância EDD

**N3 — Cross-Machine:**
- Move run para alt_machine_id
- Só se alt machine tem run com mesmo tool_id dentro da tolerância
- Insert em ordem EDD

**N4 — Split High-Earliness:**
- Runs com span > 15 dias e 2+ lots
- Split no midpoint EDD
- Cada metade recebe gate independente

### 10.2 Improvement Check

```
HARD (rejeita):
  - tardy_count new > old → REJEITA
  - otd_d new < old → REJEITA
  - earliness new > max(old, jit_earliness_target) → REJEITA

Se tardy_count diminui → ACEITA

SOFT (weighted):
  cost = setups × weight_setups + earliness × weight_earliness
  new_cost < old_cost - 0.01 → ACEITA
```

### 10.3 VNS Loop

```
k = 0 (índice do neighbourhood)
Enquanto k < 4 E total_evals < max_iter (150):
  Para cada move no neighbourhood[k]:
    Aplica move → candidato
    Recomputa gates das máquinas afectadas
    Dispatch + Score

    Se melhor:
      Aceita, k = 0 (restart)
      break

  Se não melhorou: k += 1 (próximo neighbourhood)
```

---

## 11. POST-PROCESSING

### 11.1 Fix Day Overlaps

Per machine: sort segments por (day_idx, start_min). Se `curr.start_min < prev.end_min`:
- Move start para `prev.end_min`
- Se overflow shift_b_end:
  - Se `new_day > edd` E há espaço: cap no fim do dia
  - Senão: move para próximo dia útil
- Cascade: re-scan até estabilizar (max N iterações)

### 11.2 Crew Serialization

Setup crew é 1 (partilhado entre todas as máquinas):
```
Recolher todos os setups com tempo absoluto
Ordenar cronologicamente
Para cada setup:
  Se abs_start < crew_free_at:
    Delay = crew_free_at - abs_start
    Shift start/end do segmento
    Se overflow → move para próximo dia útil
  crew_free_at = abs_start + duration

Máximo 3 passes (serialize → fix overlaps → re-serialize)
Se crew serialization piora tardy → SKIP (mantém schedule sem serialization)
```

### 11.3 Sanitize

- Remove segmentos com `start_min > end_min` (invertidos)
- Mantém segmentos com `start_min == end_min` (zero-duration EDD-protection markers)
- Clamp `start_min >= shift_a_start (420)`
- Se `end_min > shift_b_end (1440)`: move para próximo dia útil ou cap

---

## 12. PHASE 5: SCORING

### 12.1 OTD (On-Time Delivery)

```
lot_completion[lot_id] = max(day_idx) dos seus segmentos (ignora pure-setup)
tardy se completion > edd
OTD = (1 - tardy_count / n_lots) × 100
```

### 12.2 OTD-D (Demand-Day Cumulative) — CRÍTICO

```
Para cada operação:
  cum_demand = 0
  cum_produced = 0

  Pré-acumula produção de dias negativos (buffer unshift)

  Para cada dia 0..n_days:
    cum_produced += prod[op.id][dia]
    Se demand[dia] > 0:
      cum_demand += demand[dia]
      Se cum_produced < cum_demand: FAILURE

Twin handling: se segment tem twin_outputs, credita qty a cada op_id separadamente
Senão: credita ao op_id do lot

OTD-D = 100% se failures = 0
```

### 12.3 Earliness

```
Por run: gap = max(0, max_edd - last_prod_day)
earliness_avg = média de todos os gaps
```

### 12.4 Setups

```
setups = count(segmentos com setup_min > 0)
```

### 12.5 Utilisation

```
Para cada máquina:
  used = sum(prod_min + setup_min) dos seus segmentos
  total_available = (n_days - n_holidays) × DAY_CAP
  util = used / total_available × 100
```

### 12.6 Score (output completo)

```
{
  "otd": float,              # 100.0 = perfeito
  "otd_d": float,            # 100.0 = perfeito
  "otd_d_failures": int,
  "earliness_avg_days": float,
  "setups": int,
  "utilisation": {machine_id: float},
  "tardy_count": int,
  "max_tardiness": int,
  "total_tardiness": int,
  "total_segments": int,
  "total_lots": int,
}
```

---

## 13. OPERATOR ALERTS

Advisory (nunca bloqueia o scheduling):

```
Agrupa segmentos por (dia, machine_group, shift)
Conta máquinas distintas = operadores necessários

Se required > capacity:
  OperatorAlert(day_idx, date, shift, group, required, available, deficit)

Capacidades:
  Grandes: A=6, B=5
  Medias: A=9, B=4
```

---

## 14. CONSTANTES & CONFIGURAÇÃO

### 14.1 Turnos e Capacidade

| Campo | Valor | Descrição |
|---|---|---|
| shifts | `config/factory.yaml` | Turnos ativos usados pelo backend e pelo Gantt |
| day_capacity_min | soma dos turnos | Capacidade diária comum por máquina |
| DAY_CAP fallback | 1020 | Compatibilidade quando não há config carregada |

### 14.2 Produção

| Constante | Valor | Descrição |
|---|---|---|
| DEFAULT_OEE | 0.66 | Eficiência padrão |
| DEFAULT_SETUP_H | 0.5 | Setup padrão em horas |
| MIN_PROD_MIN | 1.0 | Mínimo tempo produção por lote |

### 14.3 Scheduler Tunables

| Constante | Valor | Descrição |
|---|---|---|
| MAX_RUN_DAYS | 5 | Max duração de um ToolRun |
| MAX_EDD_GAP | 10 | Gap split entre lotes consecutivos |
| MAX_EDD_SPAN | 30 | Span max dentro de um run |
| EDD_SWAP_TOLERANCE | 5 | Tolerância para reordenação |
| LST_SAFETY_BUFFER | 2 | Dias de segurança JIT |
| CAMPAIGN_WINDOW | 15 | Janela para campaign sequencing |
| URGENCY_THRESHOLD | 5 | Threshold EDD para assign EDD-aware |

### 14.4 JIT

| Constante | Valor | Descrição |
|---|---|---|
| jit_enabled | true | |
| jit_buffer_pct | 0.05 | Overhead 5% shift-boundary |
| jit_threshold | 95.0 | OTD mínimo para activar JIT |
| jit_max_retries | 15 | Iterações binary search |
| jit_earliness_target | 5.5 | Target earliness (dias) |

### 14.5 VNS

| Constante | Valor | Descrição |
|---|---|---|
| vns_enabled | true | |
| vns_max_iter | 150 | Max avaliações |

### 14.6 Subcontratação

Subcontratação é uma regra persistente por SKU em `production.sku_subcontracts`.
O campo `lead_time_days` representa a leitura documental em dias corridos; o
campo `lead_time_workdays` é o valor consumido pelo planeador. O padrão
operacional é:

| Campo | Valor | Uso |
|---|---|---|
| lead_time_days | 7 | leitura fornecedor / UI |
| lead_time_workdays | 5 | cálculo do deadline interno |
| buffer_days | 0 | margem interna adicional |

Payloads legados que enviam apenas `lead_time_days: 7` são normalizados para
`lead_time_workdays: 5`. O scheduler continua a subtrair o prazo contando dias
úteis e feriados configurados.

### 14.6 Scoring Weights

| Peso | Valor |
|---|---|
| weight_earliness | 0.40 |
| weight_setups | 0.30 |
| weight_balance | 0.30 |

---

## 15. MASTER DATA — FÁBRICA INCOMPOL

### 15.1 Máquinas (5 activas)

| Máquina | Grupo | Capacidade | Notas |
|---|---|---|---|
| PRM019 | Grandes | 1020 min | 21 SKUs |
| PRM031 | Grandes | 1020 min | 20 SKUs, Faurecia |
| PRM039 | Grandes | 1020 min | 28 SKUs, +variedade |
| PRM042 | Medias | 1020 min | 11 SKUs, SEM ALTERNATIVA |
| PRM043 | Grandes | 1020 min | 14 SKUs |

### 15.2 Alt Machines (29 ferramentas)

| Primary | Alt | Ferramentas |
|---|---|---|
| PRM031 | PRM039 | BFP079, BFP083, BFP114, BFP162, BFP171, BFP183, BFP184 |
| PRM039 | PRM043 | BFP091, BFP092, BFP096, BFP100, BFP101, BFP110, BFP178, VUL127 |
| PRM019 | PRM043 | BFP179, BFP181, BFP192, BFP197, VUL038 |
| PRM043 | PRM039 | BFP125, BFP172, BFP187, BFP204 |
| PRM019 | PRM039 | BFP080, BFP082 |
| PRM039 | PRM031 | BFP112, BFP186 |
| PRM043 | PRM031 | BFP188 |

### 15.3 Twin Pairs (14 ativos)

| Tool | SKU 1 | SKU 2 | Máquina |
|---|---|---|---|
| BFP079 | 1064169X100 | 1064186X100 | PRM031 |
| BFP083 | 1115324X080 | 1115328X080 | PRM031 |
| BFP100 | 1086227X070 | 1954311X030 | PRM039 |
| BFP101 | 1135760X070 | 1955341X030 | PRM039 |
| BFP110 | 1177295X150 | 1177297X150 | PRM039 |
| BFP125 | 1403150X050 | 1413147X070 | PRM043 |
| BFP162 | 1768601X030 | 1768602X030 | PRM031 |
| BFP171 | 2689556X090 | 2689557X090 | PRM031 |
| BFP172 | 2513974X100 | 2785359X050 | PRM043 |
| BFP178 | 2100373X120.10 | 2185094X110.10 | PRM039 |
| BFP179 | 5246946X080 | 5246947X080 | PRM019 |
| BFP186 | 3778765060.10 | 3778766060.10 | PRM039 |
| JTE004 | JJB14-000760D.10 | JJB14-000761A.10 | PRM019 |
| BTL013 | VW2872957 | VW2872960 | PRM039 |

BFP114, BFP197, VUL115 e VUL127 permanecem documentados como candidatos
pendentes de confirmação fabril. Até existir confirmação de produção simultânea
e da respetiva proporção, as suas referências são planeadas de forma independente
e conservam os eco-lotes recebidos no ISOP.

### 15.4 Setup Times

- **0.5h (30 min):** ~20 ferramentas (default)
- **1.0h (60 min):** JDE002, JTE001, JTE003, VUL031, VUL068, VUL115, etc.
- **1.25h (75 min):** BFP080, BFP082, BFP114, BFP162, VUL038
- **1.5h (90 min):** DYE025, VUL111

### 15.5 Feriados 2026

01-01, 04-03, 04-05, 04-25, 05-01, 06-04, 06-10, 08-15, 10-05, 11-01, 12-01, 12-08, 12-25

---

## 16. RESTRIÇÕES

### 16.1 HARD (nunca violar)

| Restrição | Descrição | Verificação |
|---|---|---|
| **OTD = 100%** | Total produzido ≥ total procura | `score["otd"] == 100.0` |
| **OTD-D = 100%** | Em CADA dia com procura, produção acumulada ≥ procura acumulada | `score["otd_d_failures"] == 0` |
| **Tardy = 0** | Nenhum lote completa depois do EDD | `score["tardy_count"] == 0` |
| **Shift bounds** | Todos os segmentos dentro de [420, 1440] | `seg.start_min >= 420 AND seg.end_min <= 1440` |
| **Feriados** | Nenhum segmento em dias feriados | `seg.day_idx NOT IN holidays` |
| **PRM020 fora do âmbito** | Nenhuma operação, máquina ou segmento PRM020; importações que dependam dela são recusadas | Validação na transformação |
| **Tool contention** | Mesma ferramenta nunca em 2 máquinas ao mesmo tempo | `ToolTimeline.is_available()` |
| **Equipas de setup** | Capacidade cumulativa independente por grupo (Grandes/Medias) | `setup_crews_by_group` |
| **Day capacity** | `used_per_day ≤ 1020 min` por máquina | Enforced no allocator |
| **Eco lot** | Quantidades arredondadas para cima ao lote económico | `_apply_eco_lot()` |
| **Demand conservation** | `sum(produced) ≥ sum(demanded)` por operação | OTD-D check |

### 16.2 SOFT (optimizar, verificar razoável)

| Restrição | Descrição | Target |
|---|---|---|
| **Earliness** | Média ≤ 6.5d | Target 5.5d |
| **Setups** | Não regride vs original | ~125-136 |
| **Segment overlaps** | 0 overlaps intra-máquina/dia | `_fix_day_overlaps()` |

### 16.3 STRUCTURAL

| Restrição | Descrição |
|---|---|
| **Segment start < end** | Nenhum segmento com `start_min > end_min` (= é OK para markers) |
| **Segment qty ≥ 0** | Nenhuma quantidade negativa |
| **Min prod_min** | Todos os lotes com `prod_min ≥ 1.0` ou `qty > 0` |

---

## 17. OUTPUT FINAL

### ScheduleResult

```
ScheduleResult:
  segments: list[Segment]            # ~500 blocos Gantt
  lots: list[Lot]                    # ~125 lotes
  score: dict                        # KPIs (secção 12.6)
  time_ms: float                     # runtime (< 500ms para ~60 ops)
  warnings: list[str]                # avisos textuais
  operator_alerts: list[OperatorAlert]
  audit_trail: object | None         # AuditTrail se audit=True
  journal: list[dict] | None         # telemetria por fase
```

### Capacity API

`/api/data/capacity?granularity=week` agrega dias por semana ISO e devolve
`workday_count` por máquina/grupo. A UI usa a legenda operacional:
cinzento = sem carga; vermelho = carga > capacidade.

---

## 18. TESTES — O QUE VALIDAM

### TestEcoLot
- `_apply_eco_lot(500, 0) == 500` — sem eco lot
- `_apply_eco_lot(500, 1000) == 1000` — round up
- `_apply_eco_lot(1000, 1000) == 1000` — exact
- `_apply_eco_lot(2500, 1000) == 3000` — múltiplo
- Carry-forward: surplus de dia 1 cobre dia 3
- Eco lot exhausted: 5×5000 demand + eco_lot=20000 → 2 lots

### TestLotSizing
- Solo lots: d=[0,500,0,300] → 2 lots, edd=[1,3], qty=[500,300]
- Stock NÃO é double-counted: surplus começa a 0
- No demand → 0 lots
- Min prod_min (Fix 5): micro-lot → prod_min ≥ 1.0
- Twin lot creation: 2 SKUs mesmo tool+machine → 1 lot, is_twin=True
- Twin time = max(time_A, time_B), NÃO soma

### TestToolGrouping
- Same tool grouped: 2 lots T1_M1 → 1 run, setup=60 (não 120)
- Different tools: T1 + T2 → 2 runs
- EDD sort (Fix 1): [edd=15, 5, 10] → internal [5, 10, 15], run.edd=5
- EDD gap split: edd=2 & edd=20, gap=10 → 2 runs
- Run ID format: "run_T1_M1_0"

### TestCampaignSequencing (Fix 3)
- Same tool grouped: [T1, T2, T1] → [T1, T1, T2]
- Respects tolerance: edd=50 too far → stays [T1, T2, T1]

### TestInterleaveUrgent (Fix 4)
- Breaks campaign: [T1 edd=4, T1 edd=11, T2 edd=6] → [T1, T2, T1]
- No break when not urgent: T2 edd=20 → no change

### TestTwoOpt
- Swaps to reduce setups: [T1, T2, T1] → [T1, T1, T2]

### TestAssignMachines
- No alt → primary machine
- Alt load balances: heavy M1 + light with alt → light goes to M2

### TestLST / TestJITDispatch (Fix 2)
- LST = edd - days_needed - safety_buffer
- LST with holidays: skips holiday days
- Paced LST ≤ basic LST
- JIT fallback: tardy não piora vs baseline

### TestScoring
- Perfect OTD: 100.0, tardy=0
- Tardy detection: completion day 5 > edd 2 → tardy=1, max_tardiness=3
- Earliness: day=3, edd=10 → 7.0
- Setup count: 1 segment com setup_min > 0 → setups=1

### TestScheduleAll (pipeline completo)
- Basic: d=[0,500,0,300] → 2 lots, segments > 0
- Empty: 0 lots, 0 segments
- Multi-machine: ambas as máquinas usadas
- Twin pipeline: 1 lot, is_twin=True
- Twin joint equal qty: ambos produzem max(1000, 800) = 1000
- Twin with eco lot: eco lots iguais e qty igual nos dois outputs
- Twin com eco lots diferentes: configuração bloqueada
- Twin sem procura B próxima: A e B saem 1:1; B fica como stock coproduzido
- Holidays: nenhum segmento em dia feriado
- Setup count reduced: 3 lots same tool → 1 setup
- Crew no overlap per machine
- Split across days: 50000 qty → ≥ 4 dias
- Micro-lot produces segment (Fix 5)
- Campaign reduces setups (Fix 3)
- Pipeline timing: < 500ms para 20 ops
- No production overlap per machine/day
- No overlap full factory (5 machines) after buffer

### TestHolidayEnforcement
- Nenhum segmento em dias feriados (3 testes com diferentes cargas)
- Utilisation exclui holidays no denominador

### TestCrewMutex
- Nenhum setup simultâneo entre máquinas diferentes (4 ops, 2 machines)

---

## 19. RESULTADOS VALIDADOS

| ISOP | OTD | OTD-D | Tardy | Earliness | Setups |
|---|---|---|---|---|---|
| 27/02 | 100% | 100% | 0 | 5.6d | 125 |
| 17/03 | 100% | 100% | 0 | 5.9d | 136 |

Pipeline determinístico. < 500ms para ~60 ops.

---

## 20. CPO v3.0 — META-OPTIMIZADOR GENÉTICO

### 20.1 Arquitectura

O CPO (Combinatorial Production Optimizer) envolve o pipeline greedy num Genetic Algorithm.
Cada cromossoma codifica parâmetros que alteram as decisões das Fases 1-4.

**Localização:** `scripts/cpo/`
- `optimizer.py` — Entry point, modos, fitness, GA loop
- `chromosome.py` — Encoding dos genes, mutação, crossover
- `cached_pipeline.py` — Pipeline com cache por hash do cromossoma
- `population.py` — FRRMAB, MAP-Elites, OneFifthRule, tournament selection
- `surrogate.py` — Modelo surrogate para pre-screening
- `cpsat_polish.py` — CP-SAT surgical polish nos bottlenecks

### 20.2 Cromossoma (7 Genes)

| Gene | Campo | Range | Fase | Controla |
|------|-------|-------|------|----------|
| G1 | `edd_gap` | 5-30 | Phase 2 | Split threshold por gap de EDD |
| G2 | `max_edd_span` | 10-50 | Phase 2 | Span máximo de EDDs num run |
| G3 | `machine_choice` | {idx: 0/1} | Phase 3A | Primária vs alternativa por run |
| G4 | `sequence_keys` | {machine: [float]} | Phase 3B | Ordem dos runs por máquina |
| G5 | `buffer_pct` | 0.0-0.30 | Phase 4 | Buffer JIT (% do lead time) |
| G6 | `campaign_window` | 5-30 | Phase 3B | Janela de campanha |
| G7 | `crew_priority` | [str] | Post-proc | Prioridade de máquinas na crew serialization |

### 20.3 Operadores de Mutação (9)

| Operador | Gene | Acção |
|----------|------|-------|
| `mutate_edd_gap` | G1 | Perturba ±3 |
| `mutate_edd_span` | G2 | Perturba ±5 |
| `mutate_machine` | G3 | Flip 1 run (primária ↔ alternativa) |
| `mutate_seq_swap` | G4 | Swap 2 sort keys adjacentes numa máquina |
| `mutate_seq_insert` | G4 | Relocate 1 sort key para nova posição |
| `mutate_buffer` | G5 | Perturba ±0.05 |
| `mutate_campaign` | G6 | Perturba ±3 |
| `mutate_crew_priority` | G7 | Swap 2 máquinas adjacentes na lista |
| `mutate_strong` | Todos | Shake 3-5 genes aleatórios |

**Crossover:** Uniform — 50/50 por grupo de genes. Sequence keys: 50/50 por máquina.

### 20.4 Função Fitness (`_fitness_cost()`)

```
INFEASÍVEL (tardy > 0 OR otd_d_fail > 0 OR day_cap_fail > 0):
  cost = 10000 + tardy×100 + otd_d_fail×50 + day_cap_fail×200

FEASÍVEL:
  earl_cost = earliness × 0.50
  Se earliness > 6.0d:
    earl_cost += (earliness - 6.0)² × 5.0  ← penalidade quadrática

  setup_cost = weighted_setup_cost × 0.015  ← ponderado por utilização máquina
  Fallback (sem weighted): setups × 0.20

  cost = earl_cost + setup_cost
```

**Calibração weighted_setup_cost (medido nos ISOPs):**
- ISOP 27/02: raw=1756, ×0.015=26.3 (flat=25.0) ✓
- ISOP 17/03: raw=1529, ×0.015=22.9 (flat=24.8) ✓
- Factor 0.015 dá range consistente com flat. Earl_cost típico: 2-4 para soluções boas.

**Feasibility-first:** Soluções infeasíveis recebem penalidade >10000. O GA converge primeiro para feasibilidade, depois optimiza earl+setup.

### 20.5 Weighted Setup Cost

```
Para cada segmento com setup_min > 0:
  util = total_used[machine] / total_available
  weighted_setup_cost += setup_min × min(util, 1.0)

Efeito: setup de 30 min na PRM031 (util=0.63) pesa 18.9.
         Setup de 30 min na PRM043 (util=0.40) pesa 12.0.
         → Bottleneck setups custam ~60% mais que máquinas folgadas.
```

### 20.6 Componentes Adaptativos

**FRRMAB (Fitness-Rate-Rank Multi-Armed Bandit):**
- Selecciona operador de mutação proporcionalmente ao histórico de melhoria
- Sliding window de 50 aplicações
- Reward = `max(0, best_cost - child_cost) / best_cost`
- Upper Confidence Bound para exploração

**MAP-Elites (Quality-Diversity Archive):**
- Grid 10×10 (eixos: setups × earliness)
- Mantém melhor solução por célula do grid
- Diversifica a busca — evita convergência prematura
- Baseline inserido na inicialização

**OneFifthRule:**
- Monitoriza taxa de sucesso das mutações
- Se <20% melhoram → aumenta força (mais perturbação)
- Se >20% → reduz (convergência fina)

**Surrogate Model (modos deep/max):**
- Modelo linear: features do cromossoma → custo estimado
- Pre-screening: só avalia no pipeline real se surrogate prevê custo < 1.5× best
- Treina após população inicial e a cada 10 gerações

### 20.7 Cached Pipeline (`cached_pipeline.py`)

- **Lots (Phase 1):** Gene-independent → cached UMA vez
- **ToolRuns (Phase 2):** Cached por `(edd_gap, max_edd_span)` — reutiliza entre cromossomas com mesmos G1/G2
- **Dispatch+JIT+VNS:** Full evaluation per chromosome
- **Fitness cache:** Hash MD5 do cromossoma → `(score, ScheduleResult)` — evita re-avaliação de duplicados
- **Métricas adicionais:** `day_cap_violations`, `weighted_setup_cost`
- **Crew serialization:** Passa `crew_priority` do gene G7

### 20.8 GA Loop

```
1. Inicializar população: baseline + (pop_size-1) mutantes aleatórios (1-3 mutações cada)
2. Avaliar população inicial (full pipeline por cada)
3. Para cada geração (até max_gen ou time_budget):
   a. Para cada slot na população:
      - Seleccionar operador (FRRMAB)
      - Seleccionar parent (tournament k=3)
      - Aplicar mutação
      - 30% chance: crossover com 2º parent
      - Cache check → Se hit: reutilizar score
      - Surrogate check → Se prevê mau: skip
      - Full evaluation → Score + cache + archive
      - FRRMAB reward update
      - OneFifthRule record
   b. Survivor selection: manter top pop_size por cost
   c. Re-treinar surrogate a cada 10 gerações
4. Verificar archive para melhor solução global
```

### 20.9 CP-SAT Polish (`cpsat_polish.py`)

Após o GA convergir, re-sequencia máquinas bottleneck com exact solver (OR-Tools CP-SAT).

**Identificação de bottlenecks (3 critérios):**
1. Utilização > 85%
2. Tardies nessa máquina > 0
3. Setups redundantes (mesma ferramenta consecutiva interrompida)

**Modelo CP-SAT por máquina:**
- Variáveis: posição de cada run na sequência (all-different) + start/end times
- Constraints: no-overlap via position-based ordering
- Objectivo: `minimize(sum(tardiness×1000) - sum(setup_savings))`
- Setup savings: bonus se runs com mesma ferramenta ficam adjacentes
- Warm-start com ordem actual (EDD sort)
- Time limit: 2s/máquina (normal), 10s/máquina (deep/max)
- 4 workers paralelos

**Safety:** Nunca aceita solução que piore tardy_count.

**Integração:** Corre APÓS o GA em modos normal/deep/max. Budget extra: ~4-20s dependendo do nº de bottlenecks.

### 20.10 Modos de Operação

| Modo | Pop | Gens | Budget | Surrogate | Archive | CP-SAT |
|------|-----|------|--------|-----------|---------|--------|
| quick | 0 | 0 | 0.5s | ✗ | ✗ | ✗ |
| normal | 20 | 30 | 15s | ✗ | ✓ | 2s/máq |
| deep | 40 | 100 | 120s | ✓ | ✓ | 10s/máq |
| max | 60 | 300 | 300s | ✓ | ✓ | 10s/máq |

**quick:** Apenas pipeline greedy (baseline). < 500ms.
**normal:** GA polish. ~15-20s total incluindo CP-SAT.
**deep:** + surrogate pre-screening + larger population. ~2 min.
**max:** + MAP-Elites full search. ~5 min.

### 20.11 Crew Priority (Gene G7)

**Problema:** A crew serialization corre DEPOIS do scheduling. Quando 2 setups colidem, o sweep line tem de decidir QUAL máquina cede. Sem G7, a decisão é arbitrária (ordem cronológica).

**Solução:** `crew_priority: list[str]` = permutação das 5 máquinas. Máquina com menor índice na lista tem prioridade — não é atrasada quando há colisão.

**Baseline:** Ordenado por utilização decrescente (máquina mais carregada tem prioridade).

**Crew serialization bidireccional:**
1. Sweep line ordena setups por (dia, minuto, prioridade)
2. Se setup B colide com bloqueador A:
   - Primeiro tenta PUXAR A para trás (se tem slack antes)
   - Se pull-back resolve: sem atraso para B
   - Se pull parcial: delay reduzido para B
   - Se sem espaço: empurra B para a frente (comportamento original)
3. Nunca puxa setup antes do shift_a_start (420 min)

---

## 21. STRESS MAP — ANÁLISE DE FRAGILIDADE

### `backend/scheduler/stress.py`

**Read-only:** Não modifica dados de scheduling. Análise de vulnerabilidade por segmento.

### 21.1 Fórmula

```
stress = urgency × utilisation × (1 / max(slack, 0.5))

urgency = max(0, 1 - slack / max(edd, 1))    ← 0.0 (early) a 1.0 (at EDD)
slack = max(0, edd - completion_day)           ← dias de folga
utilisation = total_used[machine] / total_available
```

### 21.2 Classificação

| Nível | Threshold | Significado |
|-------|-----------|-------------|
| critical | stress ≥ 2.0 | Qualquer disrupção causa tardy |
| warning | 1.0 ≤ stress < 2.0 | 1-2 dias de disrupção causa tardy |
| ok | stress < 1.0 | Tem folga suficiente |

### 21.3 `SegmentStress` (output)

```
SegmentStress:
  lot_id, machine_id, day_idx
  stress: float          # score numérico
  level: str             # "critical" | "warning" | "ok"
  slack_days: float      # dias de folga até EDD
  utilisation: float     # ratio utilização da máquina
```

### 21.4 `stress_summary()` (dashboard)

```
{
  total_segments, critical, warning, ok,
  fragility_pct: % de segmentos critical,
  worst_machine: máquina com maior stress médio,
  worst_machine_stress: stress médio da pior máquina,
  top_fragile: top 5 segmentos mais frágeis [lot, machine, day, stress, slack]
}
```

Segmentos com `day_idx < 0` (buffer) ou `prod_min <= 0` (setup-only) são ignorados.

---

## 22. FICHEIROS CHAVE — REFERÊNCIA RÁPIDA

| Ficheiro | Linhas | Fase | Responsabilidade |
|----------|--------|------|------------------|
| `backend/parser/isop_reader.py` | ~200 | Input | Parser XLSX → RawRow[] |
| `backend/transform/transform.py` | ~300 | Input | RawRow[] → EngineData |
| `backend/scheduler/lot_sizing.py` | 249 | Phase 1 | EOps → Lots (eco lot, twins, carry-forward) |
| `backend/scheduler/tool_grouping.py` | 166 | Phase 2 | Lots → ToolRuns (split, infeasibility) |
| `backend/scheduler/dispatch.py` | 523 | Phase 3 | Assign + Sequence + Allocate |
| `backend/scheduler/jit.py` | 321 | Phase 4 | Libertação de material e fallback |
| `backend/scheduler/vns.py` | 365 | Phase 4b | VNS polish (4 neighbourhoods) |
| `backend/scheduler/scheduler.py` | 586 | All | Orchestrator, buffer, crew, post-proc |
| `backend/scheduler/scoring.py` | 147 | Phase 5 | OTD, OTD-D, earliness, setups |
| `backend/scheduler/stress.py` | 158 | Analysis | Stress map (read-only) |
| `backend/scheduler/types.py` | 126 | — | Lot, ToolRun, Segment, ScheduleResult |
| `backend/types.py` | 99 | — | RawRow, EOp, TwinGroup, EngineData |
| `backend/config/types.py` | 139 | — | ShiftConfig, MachineConfig, FactoryConfig |
| `scripts/cpo/optimizer.py` | 380 | CPO | Entry point, modes, fitness, GA loop |
| `scripts/cpo/chromosome.py` | 245 | CPO | 7 genes, 9 operators, crossover |
| `scripts/cpo/cached_pipeline.py` | 254 | CPO | Cached pipeline evaluation |
| `scripts/cpo/population.py` | ~200 | CPO | FRRMAB, MAP-Elites, OneFifthRule |
| `scripts/cpo/surrogate.py` | ~100 | CPO | Surrogate model |
| `scripts/cpo/cpsat_polish.py` | 290 | CPO | CP-SAT bottleneck polish |

---

## 23. INVARIANTES DO SISTEMA

1. **OTD = 100%** — OBRIGATÓRIO, qualquer regressão é bug
2. **OTD-D = 100%** — cumulative production ≥ cumulative demand em CADA dia
3. **tardy_count = 0** — nenhum lot completa após EDD
4. **DAY_CAP nunca excedido** — max 1020 min/dia/máquina
5. **Eco lot HARD** — produção sempre arredondada para cima
6. **Twins simultâneos** — num ciclo conjunto, `qty_A = qty_B` e tempo = max(A,B)
7. **1 crew para setups** — nunca 2 setups em paralelo (com G7 priority)
8. **Pipeline greedy determinístico** — mesmo input → mesmo output
9. **CPO safety net** — resultado CPO nunca pior que baseline greedy
10. **CP-SAT safety** — nunca aceita solução que piore tardy_count
