# Motor de Scheduling PP1 — Algoritmos

## 1. ATCS (Apparent Tardiness Cost with Setups)

### Fórmula

```
Prioridade(j) = (w_j / p_j) × exp(-max(slack_j, 0) / (k1 × p̄)) × exp(-s_prev,j / (k2 × s̄))
```

**Termo 1 — Urgência/Tempo (WSPT modificado)**:
- `w_j` = peso da encomenda j (default 1.0; penalidades por atraso aumentam)
- `p_j` = tempo de processamento da encomenda j = |NP| / (pH × OEE)
- Rácio w/p: encomendas curtas e urgentes têm prioridade natural

**Termo 2 — Penalização de Folga (OTD)**:
- `slack_j` = deadline_j - tempo_actual - p_j (folga restante)
- `k1` = parâmetro de sensibilidade à folga (típico: 1.0-3.0)
- `p̄` = tempo médio de processamento de todos os jobs pendentes
- Quando slack → 0: exp(0) = 1.0 (prioridade máxima)
- Quando slack >> 0: exp(-grande) → 0 (prioridade baixa)

**Termo 3 — Penalização de Setup**:
- `s_prev,j` = tempo de setup para trocar da ferramenta actual para a de j
- `k2` = parâmetro de sensibilidade ao setup (típico: 1.0-2.5)
- `s̄` = tempo médio de setup de todos os jobs
- Se mesma ferramenta (s=0): exp(0) = 1.0 (sem penalização)
- Se setup longo: exp(-grande) → 0 (prioridade reduzida)

### Grid Search de k1/k2

```
Pseudocódigo:

FUNÇÃO calibrar_k1_k2(jobs, máquinas, config):
  k1_range = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
  k2_range = [0.5, 1.0, 1.5, 2.0, 2.5]
  melhor_score = +∞
  melhor_k1, melhor_k2 = 1.5, 1.5  // defaults

  PARA k1 EM k1_range:
    PARA k2 EM k2_range:
      schedule = executar_ATCS(jobs, máquinas, k1, k2)
      score = avaliar(schedule, config.weights)
      SE score < melhor_score:
        melhor_score = score
        melhor_k1, melhor_k2 = k1, k2

  RETORNAR melhor_k1, melhor_k2

FUNÇÃO avaliar(schedule, weights):
  T = soma(max(0, conclusão_j - deadline_j)) para todo j  // tardiness total
  S = contagem de setups
  U = 1 - média(utilização por máquina)                   // ociosidade
  RETORNAR weights.otd × T + weights.setup × S + weights.util × U
```

Tipicamente 25-36 combinações. Tempo total <50ms para 100 jobs.

## 2. Simulated Annealing (Busca Local)

```
Pseudocódigo:

FUNÇÃO SA_refinamento(schedule_inicial, config):
  schedule = copiar(schedule_inicial)
  melhor = copiar(schedule)
  T = temperatura_inicial        // 100-500 (depende da escala do objectivo)
  T_min = 0.1
  alpha = 0.995                  // taxa de arrefecimento
  max_iter = 10000

  PARA iter = 1 ATÉ max_iter:
    // Gerar vizinho
    tipo = escolher_aleatório(['swap', 'insert', 'inter_machine'])

    SE tipo == 'swap':
      // Trocar 2 operações adjacentes na mesma máquina
      m = máquina_aleatória()
      i, j = dois_índices_adjacentes(schedule[m])
      vizinho = trocar(schedule, m, i, j)

    SE tipo == 'insert':
      // Mover operação para outra posição na mesma máquina
      m = máquina_aleatória()
      i = índice_aleatório(schedule[m])
      j = posição_aleatória(schedule[m])
      vizinho = inserir(schedule, m, i, j)

    SE tipo == 'inter_machine':
      // Mover operação entre máquinas (só se alt machine existe)
      op = operação_com_alternativa_aleatória()
      m_destino = máquina_alternativa(op)
      vizinho = mover_entre_máquinas(schedule, op, m_destino)

    // Avaliar
    delta = avaliar(vizinho) - avaliar(schedule)
    SE delta < 0 OU random() < exp(-delta / T):
      schedule = vizinho
      SE avaliar(schedule) < avaliar(melhor):
        melhor = copiar(schedule)

    T = T × alpha
    SE T < T_min: PARAR

  RETORNAR melhor
```

**Restrições**:
- Executa em Web Worker (nunca main thread)
- Tempo máximo: 3 segundos
- Melhoria típica: 5-15% sobre ATCS puro
- Todas as 4 constraints verificadas em cada vizinho

## 3. Replaneamento por Camadas

### Camada 1: Right-Shift (< 30 min perturbação)

```
Pseudocódigo:

FUNÇÃO right_shift(schedule, perturbação):
  // perturbação = {máquina, início_impacto, duração_impacto}
  atraso = perturbação.duração
  m = perturbação.máquina

  PARA CADA op EM schedule[m] ORDENADAS POR início:
    SE op.início >= perturbação.início_impacto:
      op.início += atraso
      op.fim += atraso

  // Propagar para operações dependentes (mesma ferramenta noutras máquinas)
  PARA CADA op_afectada:
    verificar_constraint_tool(op_afectada)
    verificar_constraint_setup_crew(op_afectada)

  RETORNAR schedule
```

Complexidade: O(n). Sem resequenciação.

### Camada 2: Match-Up (30 min - 2h)

```
Pseudocódigo:

FUNÇÃO match_up(schedule, perturbação, horizonte_convergência):
  // Reescalonar desde perturbação até convergir com plano original
  ponto_impacto = perturbação.início_impacto
  zona_replan = extrair_operações(schedule, ponto_impacto, horizonte_convergência)

  // Re-executar ATCS apenas para a zona afectada
  sub_schedule = executar_ATCS(zona_replan, máquinas_afectadas, k1, k2)

  // Merge: zona replaneada + resto do plano original
  schedule_final = merge(sub_schedule, schedule, horizonte_convergência)

  RETORNAR schedule_final
```

### Camada 3: Parcial (> 2h)

```
Pseudocódigo:

FUNÇÃO replan_parcial(schedule, perturbação):
  // Propagar impacto por grafo de dependências
  afectadas = propagar_impacto(perturbação, schedule)
  // afectadas inclui: mesma máquina, mesma ferramenta, mesmos calços

  não_afectadas = schedule - afectadas
  novo_sub = executar_ATCS(afectadas, máquinas_disponíveis, k1, k2)
  novo_sub = SA_refinamento(novo_sub, config_rápida)  // max 1 seg

  RETORNAR merge(não_afectadas, novo_sub)
```

### Camada 4: Regeneração Total (catástrofe)

```
FUNÇÃO regeneração_total(dados_actuais, schedule_anterior):
  // Usar schedule anterior como semente para k1/k2
  k1, k2 = calibrar_k1_k2(dados_actuais.jobs, dados_actuais.máquinas)
  novo = executar_ATCS(dados_actuais.jobs, dados_actuais.máquinas, k1, k2)
  novo = SA_refinamento(novo, config_padrão)
  RETORNAR novo
```

### Turno Noite Automático

```
FUNÇÃO verificar_necessidade_noite(schedule):
  PARA CADA máquina m:
    PARA CADA dia d:
      carga = soma(duração) de operações em m no dia d
      SE carga > 1020 min:  // 2 turnos = 1020 min
        // Verificar se há ops tardy que beneficiariam
        ops_tardy = operações com conclusão > deadline em m
        SE ops_tardy NÃO VAZIO:
          activar_turno_noite(m, d)  // +420 min (00:00-07:00)
          resequenciar(m, d)         // redistribuir ops pelos 3 turnos
```

## 4. Peças Gémeas no Scheduler

```
Pseudocódigo:

FUNÇÃO agendar_gémeas(par_gémeo, schedule):
  // par_gémeo = {op_A, op_B, ferramenta, máquina}
  qty_A = |NP_A|   // quantidade da peça A
  qty_B = |NP_B|   // quantidade da peça B

  // Tempo baseado no máximo (produção simultânea)
  qty_máquina = max(qty_A, qty_B)
  tempo = qty_máquina / (pH × OEE)

  // Criar bloco único
  bloco = {
    ferramenta: par_gémeo.ferramenta,
    máquina: par_gémeo.máquina,
    duração: tempo,
    setup: ferramenta.setup_hours,  // 1 setup, não 2
    operadores: ferramenta.operadores,  // reservados 1x, não 2x
    output_A: qty_A,  // cada SKU recebe exactamente o que precisa
    output_B: qty_B,
  }

  // Agendar como operação única
  inserir_no_schedule(bloco, schedule)
```

**Regras críticas**:
- Output A ≠ Output B (cada SKU recebe a SUA quantidade)
- Tempo = max(A, B), NUNCA sum(A, B)
- 1 setup, 1 corrida de máquina
- Cross-EDD: emparelhar por ordem sequencial (1ª com 1ª, 2ª com 2ª)
- EDD do par = min(deadline_A, deadline_B)

## 5. Setup Matrix por Famílias de Ferramenta

```
Pseudocódigo:

FUNÇÃO construir_setup_matrix(ferramentas):
  // Agrupar ferramentas em famílias (~8-15 famílias)
  // Critério: ferramentas da mesma máquina com características similares
  famílias = agrupar_por_máquina_e_tipo(ferramentas)

  // Exemplo Incompol:
  // Família BFP-Grande: BFP079, BFP080, BFP082, BFP083 (PRM031, setup 1.0-1.25h)
  // Família BFP-Pequena: BFP171, BFP172, BFP178, BFP179 (setup 0.5h)
  // Família VUL: VUL031, VUL038, VUL068, VUL111, VUL115 (setup 1.0-1.5h)
  // Família JTE: JTE001, JTE003 (PRM043, setup 1.0h)

  // Matriz NxN (família × família)
  matrix = {}
  PARA CADA par (fam_i, fam_j):
    SE fam_i == fam_j:
      matrix[fam_i][fam_j] = 0  // sem mudança de ferramenta
    SENÃO:
      matrix[fam_i][fam_j] = max(setup_fam_i, setup_fam_j)  // tempo da troca

  RETORNAR matrix

FUNÇÃO delta_setup(schedule, máquina, posição, op_nova, matrix):
  // Calcular custo incremental de inserir op_nova na posição
  // O(1) via matrix lookup
  fam_antes = família(schedule[máquina][posição - 1])
  fam_depois = família(schedule[máquina][posição])
  fam_nova = família(op_nova)

  custo_antes = matrix[fam_antes][fam_depois]
  custo_depois = matrix[fam_antes][fam_nova] + matrix[fam_nova][fam_depois]

  RETORNAR custo_depois - custo_antes
```

## 6. Tempos de Setup Reais (Incompol)

| Setup (h) | Ferramentas |
|-----------|-------------|
| 0.50 | BFP112, BFP171, BFP172, BFP178, BFP179, BFP181, BFP183, BFP184, BFP186, BFP187, BFP188, BFP192, BFP195, BFP197, BFP202, BFP204, EBR001, HAN002, HAN004, LEC002, MIC009 |
| 1.00 | BFP079, BFP083, BFP091, BFP092, BFP096, BFP100, BFP101, BFP110, BFP125, BTL013, BWI003, JDE002, JTE001, JTE003, JTE004, JTE007, VUL031, VUL068, VUL115, VUL125, VUL127, VUL128, VUL146, VUL147, VUL173, VUL174, VUL192, VUL195, VUL199, VUL201, VUL203 |
| 1.25 | BFP080, BFP082, BFP114, BFP162, VUL038 |
| 1.50 | DYE025, VUL111 |
