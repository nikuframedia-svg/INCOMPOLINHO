# ProdPlan PP1 — Industrial APS Scheduler

Scheduler de produção para fábricas de estampagem.
Fábrica: Incompol (5 prensas, 59 ferramentas, ~94 SKUs, 14 clientes).
Empresa: NIKUFRA.AI (Portugal).

## Arquitectura

- `backend/` — Python: Scheduler + Analytics + Simulator + Parser + Transform + Copilot LLM (`backend/copilot/`)
- `frontend/` — React 19 + TypeScript + Vite + Zustand (UI: Console, Gantt, Stock, Risk, Expedition, Simulator, Config, Journal, Rules)
- `config/incompol.yaml` — Master data (máquinas, setups, twins, holidays)
- `docker/` + `Dockerfile` + `docker-compose.yml` — Orquestração multi-stage (Node build → Python slim + Nginx + Supervisor)
- `tests/` — 414 testes (backend Python)

## Comandos
```bash
python -m pytest tests/ -v
```

## Pipeline

```
ISOP Excel (.xlsx)
  ↓ read_isop()                [backend/parser/isop_reader.py]
RawRow[]
  ↓ transform()                [backend/transform/transform.py]
EngineData
  ↓ optimize()                 [backend/cpo/optimizer.py]
ScheduleResult { segments, lots, score, warnings, operator_alerts }
```

## ═══ CPO v3.0 — Cascading Pipeline Optimizer ═══

Entry point: `from backend.cpo import optimize`
Modos: quick (greedy passthrough), normal (GA 20×30 + CP-SAT), deep (GA 40×100 + surrogate), max (GA 60×300)

- `optimize(data, mode="quick")` — mesmo que schedule_all(), <500ms
- `optimize(data, mode="normal")` — GA optimiza 7 genes sobre o greedy, ~5-15s
- `schedule_all()` — pipeline greedy interno (5 fases), chamado pelo CPO internamente

Todos os callers externos usam `optimize()`. `schedule_all()` é interno.

## ═══ PRIORIDADE Nº1 ═══
ENTREGAR TUDO A TEMPO. Sem excepção.

## ═══ OTD-DELIVERY = 100% (OBRIGATÓRIO) ═══

- **OTD** (global) = total produzido >= total procura → 100%
- **OTD-D** (por dia) = em CADA dia com procura, produção acumulada >= procura acumulada → 100%
- Qualquer regressão abaixo de 100% é um BUG

## ═══ DADOS ISOP ═══

Colunas: A(Cliente) B(Nome) C(SKU) D(Designação) E(Lote Eco—HARD)
G(Máquina) H(Ferramenta) I(Peças/H) J(Pessoas) L(WIP) M(Gémea) N(Atraso)
O+(Datas ~80 dias—FONTE PRINCIPAL)

IGNORAR SEMPRE: F(Prz.Fabrico) e K(STOCK-A)

Valores NP nas datas:
- Positivo (preto) = STOCK REAL disponível
- Negativo (vermelho) = ENCOMENDA INDEPENDENTE (NÃO cumulativo)
  |valor| = qtd a produzir, data coluna = deadline
- Vazio = sem dados

Stock real = último positivo antes do primeiro negativo.
Lote económico: HARD — arredonda sempre para cima ao eco lot.

## ═══ PEÇAS GÉMEAS ═══
Mesma ferramenta + máquina, produção SIMULTÂNEA.
Quantidade por SKU = exactamente o que precisa (eco lot per-SKU).
Tempo = UMA execução (max(time_A, time_B), não dobro).
Surplus carry-forward independente por SKU.

## ═══ MÁQUINAS ═══
PRM019(Grandes,21SKUs) PRM031(Grandes,20,Faurecia) PRM039(Grandes,28,+variedade)
PRM042(Médias,11,SEM ALTERNATIVA) PRM043(Grandes,14)
PRM020 — FORA DE USO. IGNORAR.

## ═══ TURNOS ═══
Turno A: 07:00-15:30 (510 min) | Turno B: 15:30-00:00 (510 min)
DAY_CAP = 1020 min. Noite: SÓ EMERGÊNCIA.

## ═══ SCHEDULER — 5 FASES ═══

1. **Lot Sizing** (lot_sizing.py): EOps → Lots. Eco lot HARD + carry-forward + twins.
2. **Tool Grouping** (tool_grouping.py): Lots → ToolRuns. Split por EDD gap e infeasibilidade.
3. **Dispatch** (dispatch.py): Assign machines (EDD-aware) + Sequence (campaign + interleave urgent + 2-opt) + Allocate segments.
4. **JIT** (jit.py): Backward scheduling. Produzir o mais tarde possível (2-5 dias antes EDD). Safety net: fallback se tardy piora.
5. **Scoring** (scoring.py): OTD, OTD-D, earliness, setups, utilisation.

## ═══ CONSTANTES ═══
DAY_CAP=1020 | SHIFT_A=420-930 | SHIFT_B=930-1440
DEFAULT_OEE=0.66 | DEFAULT_SETUP=0.5h | MIN_PROD_MIN=1.0
MAX_RUN_DAYS=5 | MAX_EDD_GAP=10 | LST_SAFETY_BUFFER=2
EDD_SWAP_TOLERANCE=5

## ═══ PÓS-PROCESSAMENTO (scheduler.py) ═══

Após dispatch + JIT + VNS + crew serialization, 3 funções de pós-processamento:

1. **`_fix_day_overlaps`**: Corrige sobreposições intra-dia. Empurra segmentos para o dia seguinte se não cabem (com EDD guard). Pode criar "zero-duration placeholders" quando EDD bloqueia o push.
2. **`_sanitize_segments`** (2 passes):
   - Pass 1: remove invertidos, clamp start≥420, cap end≤1440
   - Pass 2: detecta **ghost segments** (`duration < prod_min + setup_min`) — tenta relocar para dia anterior com capacidade via `_try_relocate_truncated`, senão trunca proporcionalmente ou remove
3. **`_fix_orphan_continuations`**: Reseta `is_continuation=False` no primeiro segmento de cada lot (corrige flags erradas de `_fix_day_overlaps`)

## ═══ BUGS CORRIGIDOS ═══

### Crew Buffer Day Fix (2026-04-08)
**Bug**: `_serialize_crew_setups` e `_serialize_crew_safe` filtravam `seg.day_idx >= 0`, ignorando setups em buffer days (dias negativos). `crew_free_at` começava a 0.0, fazendo com que setups com abs_time negativo nunca fossem processados. Resultado: setups simultâneos em máquinas diferentes nos buffer days.
**Fix**: Removido filtro `day_idx >= 0`. `crew_free_at` inicializado ao `min(abs_times)` dos setups. Ambos os ISOPs validados: 0 crew overlaps em todos os dias (reais e buffer).

### Ghost Segment Fix (2026-04-08)
**Bug**: `_fix_day_overlaps` criava segmentos com `start=end=1440` (zero duração) mas mantinha `prod_min`/`qty` intactos quando EDD impedia push para dia seguinte. Resultado: produção fantasma contabilizada no scoring mas fisicamente impossível. Caso real: PRM019 dia 67 declarava 1413 min (cap=1020), com 7200 pç de BFP179 que nunca seriam produzidas.
**Fix**: `_sanitize_segments` Pass 2 detecta `duration < prod_min + setup_min` e chama `_try_relocate_truncated` que procura dia anterior com capacidade (verifica shift bounds). No caso real, relocou para dia 65 (livre, EDD=67). OTD-D mantém-se 100%.

### Orphan Continuation Fix (2026-04-08)
**Bug**: `_fix_day_overlaps` marcava `is_continuation=True` incondicionalmente ao empurrar segmentos, mesmo quando o segmento era o primeiro do lot. 25 segmentos ficavam como "continuação" sem precedente visível no Gantt.
**Fix**: `_fix_orphan_continuations` identifica o primeiro segmento de cada lot (ordenado por day_idx, start_min) e reseta a flag.

## ═══ RESULTADOS VALIDADOS ═══
ISOP 27/02: OTD=100%, OTD-D=100%, 0 tardy, earliness=5.4d, 125 setups
ISOP 17/03: OTD=100%, OTD-D=100%, 0 tardy, earliness=5.9d, 136 setups
414 testes passam. Pipeline determinístico. <500ms para ~60 ops.
0 violações de capacidade. 0 ghost segments. 0 orphan continuations.
