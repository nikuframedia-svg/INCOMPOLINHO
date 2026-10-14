# ProdPlan PP1 — Industrial APS Scheduler

> **`AGENTS.md` prevalece sobre este ficheiro.** Define o contrato de planeamento
> (física → entregas por encomenda → antecipação → setups/transferências) e as
> decisões confirmadas. O que aqui contradiga o AGENTS.md é histórico.

Scheduler de produção para fábricas de estampagem.
Fábrica: Incompol (5 prensas, 59 ferramentas, ~94 SKUs, 14 clientes).
Empresa: NIKUFRA.AI (Portugal).

## Arquitectura

- `backend/` — Python: Scheduler + Analytics + Simulator + Parser + Transform + Copilot LLM (`backend/copilot/`)
- `frontend/` — React 19 + TypeScript + Vite + Zustand (UI: Console, Gantt, Stock, Risk, Expedition, Simulator, Config, Journal, Rules)
- `config/incompol.yaml` — Master data (máquinas, setups, twins, holidays)
- `docker/` + `Dockerfile` + `docker-compose.yml` — Orquestração multi-stage (Node build → Python slim + Nginx + Supervisor)
- `tests/` — ~2780 testes (backend Python); casos reais congelados em `tests/fixtures/private/` (fora do git)

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
Modos: quick (greedy passthrough), normal (num ISOP real, ≥50 operações: greedy + ciclo de melhoria sem perdas; em instâncias pequenas também pesquisa candidatos e CP-SAT local), deep/max (pesquisa de candidatos + CP-SAT local + ciclo de melhoria; diferem no orçamento). O GA não é operacional: vive em `backend/cpo/offline_ga.py` só para experiências offline.

- `optimize(data, mode="quick")` — mesmo que schedule_all(), <500ms
- `optimize(data, mode="normal")` — melhoria limitada e validada sobre o greedy (critério canónico em `backend/scheduler/policy.py`, ver `AGENTS.md`)
- `schedule_all()` — pipeline greedy interno (5 fases), chamado pelo CPO internamente

Todos os callers externos usam `optimize()`. `schedule_all()` é interno.

## ═══ ENTREGAS ═══
Entregar a tempo é o primeiro objetivo **depois das leis físicas** (máquina,
ferramenta, equipa, calendário, material) e do lote económico numa só produção.
O lote económico numa só produção é **regra dura, acima da entrega a tempo**
(decisão do Luís, 13/10/2026; verificação `lot_split` no gate): se o lote
atrasa outra encomenda, move-se inteiro; nunca se parte para a salvar. Pode
atrasar uma entrega quando o lote não cabe inteiro antes do prazo (visto num
ensaio de 13/10, revisão 128, avaria grande da PRM031 a 16/10: uma entrega um
dia atrasada) e traz mais stock e produção mais cedo: +39% peças × dias e 44
entregas com mais de 30 dias de antecedência na carga de ISOP nova de 13/10;
+39% e 52 no recálculo F1 do golden master (AGENTS §1.1). Quando há
capacidade, o alvo é OTD = OTD-D = 100%.

- **OTD** (global) = total produzido >= total procura
- **OTD-D** (por dia) = em cada dia com procura, produção acumulada >= procura acumulada
- Uma melhoria automática nunca pode piorar **nenhuma** encomenda individual.
- **Subcontratadas (Luís, 14/10/2026):** só estão atrasadas se faltar stock
  no ecrã de Entregas no dia da entrega (peças contam no dia em que são
  feitas), em todo o sistema e sem opção. O motor continua a apontar para
  acabar 5 dias úteis antes (envio), mas falhar isso não é atraso nem
  aparece no ecrã (AGENTS §2).
- Se não há capacidade dentro da janela de material, o plano mantém e reporta
  os atrasos: nunca relaxar a janela, inventar stock ou violar física para
  mostrar 100%. Ex.: revisão 90 tem OTD 96,5% por falta real de capacidade
  na PRM042 (sem alternativa).

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
Lote económico: HARD — é o MÍNIMO; nunca múltiplos. Lote = max(lote económico,
necessidade) (decisão do Luís, 14/10/2026; AGENTS §2).

## ═══ LOTE ECONÓMICO = UMA PRODUÇÃO (decisão do Luís, 13/10/2026) ═══
Regra da Incompol; detalhe no `AGENTS.md` §2 («Lote económico = uma produção»).
Estado: implementada a 13/10/2026 (contrato de material versão 3). Planos antigos
continuam válidos (não pedem «Recalcular»); o «Recalcular plano» redimensiona-os.
- Sempre que se produz um SKU, produz-se pelo menos o lote económico, numa só
  produção (um setup). O lote económico cumpre-se sempre.
- **Lote económico = mínimo, nunca múltiplos (14/10/2026, versão 4):** se a
  necessidade da entrega que abre o lote é maior do que o lote económico,
  produz-se essa quantidade (27 641 com lote de 23 040 → 27 641, não 46 080).
  Planos das versões 1-3 (arredondados) são reconstruídos pelo «Recalcular
  plano»; num replaneamento os lotes começados mantêm o tamanho antigo
  (regra 4) e contam como oferta já comprometida.
- A janela de 5 dias úteis de matéria-prima vale só para a PRIMEIRA entrega que
  o lote serve. As outras entregas que o lote cobre e o excedente não têm janela
  própria: considera-se que há MP para o lote económico inteiro.
- Nunca partir um lote em produções separadas. Se atrasar outra encomenda,
  move-se o lote inteiro (mais cedo, mais tarde ou para a máquina alternativa).
- Gémeas: o ciclo usa o `R` da primeira entrega de qualquer dos lados.
- Subcontratados (implementado a 14/10/2026): o lote inteiro vai ao
  subcontratado quando acaba e volta todo em fim do lote + prazo (dias úteis);
  todas as entregas do lote ficam prontas nesse dia; tem de acabar até ao
  último envio `H` da primeira entrega (`material_quantities.whole_lot_subcontract`).
- Um lote nunca para com tempo de turno livre pelo meio, nem é interrompido
  por outro trabalho; só uma avaria ou bloqueio sobre o tempo de trabalho
  entre as partes o desculpa. Lotes de planos antigos (v1-2) podem manter as
  produções que tinham, mas não ganhar outra.
- A janela por entrega (07–11/10/2026) partia os lotes e subiu os setups de
  ~3 para ~9 por dia; não voltar a ela.

## ═══ PEÇAS GÉMEAS ═══
Mesma ferramenta + máquina, produção SIMULTÂNEA.
Quantidade por ciclo = a maior das necessidades dos dois lados (cada uma pelo
menos o seu lote económico, sem arredondar); os dois SKUs recebem essa quantidade.
Tempo = UMA execução (max(time_A, time_B), não dobro).
Surplus carry-forward independente por SKU.

## ═══ MÁQUINAS ═══
PRM019(Grandes,21SKUs) PRM031(Grandes,20,Faurecia) PRM039(Grandes,28,+variedade)
PRM042(Médias,11,SEM ALTERNATIVA) PRM043(Grandes,14)
PRM020 — fora do âmbito da análise; não importar procura nem criar capacidade nesta máquina.

## ═══ TURNOS ═══
Turno A: 07:00-15:30 (510 min) | Turno B: 15:30-00:00 (510 min)
DAY_CAP = 1020 min. Noite: SÓ EMERGÊNCIA.

## ═══ SCHEDULER — 5 FASES ═══

1. **Lot Sizing** (lot_sizing.py): EOps → Lots. Lote económico mínimo (max(eco, necessidade)) + carry-forward + twins.
2. **Tool Grouping** (tool_grouping.py): Lots → ToolRuns. Split por EDD gap e infeasibilidade.
3. **Dispatch** (dispatch.py): Assign machines (EDD-aware) + Sequence (campaign + interleave urgent + 2-opt) + Allocate segments.
4. **JIT** (jit.py): Histórico. O objetivo atual é o oposto: produzir o mais cedo possível após a libertação de material (5 dias úteis); ver `AGENTS.md`, que prevalece sobre este ficheiro. Setups extra desempatam, não vetam (decisão 02/10/2026).
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

## ═══ RESULTADOS ═══
Históricos (política antiga JIT, não comparáveis): ISOP 27/02 e 17/03 com
OTD=100%, 125/136 setups, <500ms no modo quick.

Atuais (lote económico = uma produção, decisão de 13/10; ensaio de 14/10
numa cópia da revisão 128, ISOP 13/10): 0 violações físicas, 0 lotes
partidos, 0 produção antes do `R` do lote; 178 setups (antes 445), 1 entrega
atrasada (HAN002 de 16/10, lote já para lá do envio, igual a antes); cada
recálculo < 60 s (~44 s). Revisão 90 (ISOP 17/09): 5 atrasados (antes 11),
188 setups (antes 538). Custo da regra: mais stock e produção mais cedo
(AGENTS §1.1, §2). Com corte por tempo o resultado **não é garantidamente
determinístico** (AGENTS §6).

Anteriores (revisão 90, janela por entrega, recálculo a 02/10, 1 núcleo):
OTD 96,5%, OTD-D 99,1%, 7 atrasados (capacidade PRM042); ciclo de melhoria
~11,5 s p50, 128 MiB. Ver `docs/plano-solver-2026-10-02.md` §10–12.
