# ProdPlan PP1 — Industrial APS Scheduler

Scheduler de produção para fábricas de estampagem.
Fábrica: Incompol (5 prensas, 59 ferramentas, ~94 SKUs, 14 clientes).
Empresa: NIKUFRA.AI (Portugal).

## Arquitectura

Python puro. Sem frontend. Sem monorepo.
- `backend/` — Scheduler + Analytics + Simulator + Parser + Transform
- `config/incompol.yaml` — Master data (máquinas, setups, twins, holidays)
- `tests/` — 86+ testes

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

## ═══ RESULTADOS VALIDADOS ═══
ISOP 27/02: OTD=100%, OTD-D=100%, 0 tardy, earliness=5.6d, 125 setups
ISOP 17/03: OTD=100%, OTD-D=100%, 0 tardy, earliness=5.9d, 136 setups
346 testes passam. Pipeline determinístico. <500ms para ~60 ops.
