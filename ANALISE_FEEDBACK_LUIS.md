# Analise Completa — Feedback do Luis sobre o PP1

**Data:** 8 Abril 2026
**Contexto:** O Luis testou o PP1 (scheduler de producao da Incompol) e reportou 7 pontos antes da apresentacao. Este documento explica cada problema em profundidade, a causa tecnica, e a solucao proposta.

---

## Indice
1. [Fundo branco / aspeto tradicional](#1-fundo-branco)
2. [Bug: Preset "esquece" simulacao](#2-bug-preset-simulacao)
3. [Presets sem indicacao de ativo](#3-presets-visual)
4. [BFP114 nao antecipada](#4-bfp114)
5. [SKU no Gantt em vez de ferramenta](#5-sku-gantt)
6. [BFP202 repeticao desnecessaria](#6-bfp202)
7. [Lead times BFP178 / BFP186](#7-lead-times)

---

## 1. Fundo Branco / Aspeto Tradicional {#1-fundo-branco}

### O que o Luis reportou
> "Mudanca da cor do fundo para branco, o programa esta simples o suficiente para uso, mas tem um aspeto muito 'high tech' queremos numeros, letras e design um pouco mais tradicional."

### O que esta a acontecer
A aplicacao usa um tema escuro inspirado na Apple — fundo preto (#000000), texto branco, cards cinza escuro. Todas as cores estao definidas num unico ficheiro (`frontend/src/theme/tokens.ts`):

```
bg: "#000000"        ← fundo principal (preto)
card: "#0D0D0D"      ← fundo dos cards (quase preto)
elevated: "#161616"  ← elementos elevados (cinza muito escuro)
primary: "#F5F5F7"   ← texto principal (quase branco)
secondary: "#86868B" ← texto secundario (cinza)
```

Estas cores sao importadas em TODOS os componentes da app. Nao existe botao de toggle dark/light — o tema e hardcoded.

O ficheiro `index.html` tambem tem cores fixas:
```html
background: #000000;
color: rgba(255,255,255,0.92);
```

### Porque e que foi feito assim
Tema dark e comum em apps industriais modernas (dashboards, SCADA). Mas para um planeador de producao que vai ser usado no chao de fabrica ou em reunioes com Excel aberto ao lado, o aspeto "high tech" pode ser um obstaculo — os utilizadores estao habituados a Excel (fundo branco, texto preto).

### Solucao proposta
Redefinir o objeto de cores para palette light:
- Fundo: branco (#FFFFFF)
- Cards: cinza muito claro (#F5F5F7)
- Texto: preto (#1D1D1F)
- Secundario: cinza medio (#6E6E73)
- Borders: preto a 8% de opacidade

**Risco importante:** Os blocos do Gantt sao desenhados com cores a 13% de opacidade sobre o fundo (ex: `background: #FF453A22`). Sobre fundo preto, isto cria um efeito subtil bonito. Sobre fundo branco, fica quase invisivel. Precisamos de aumentar a opacidade para 40-60% e reforcar os borders.

### Ficheiros envolvidos
- `frontend/src/theme/tokens.ts` — objeto de cores (27 linhas)
- `frontend/index.html` — background e scrollbar global
- `frontend/src/pages/GanttPage.tsx` — opacidade dos blocos, contraste texto
- Potencialmente todos os componentes que usam cores do tema

### Esforco estimado
Medio. 2-3 horas com teste visual em todas as paginas.

---

## 2. Bug: Preset "Esquece" Simulacao (CRITICO) {#2-bug-preset-simulacao}

### O que o Luis reportou
> "Quando simulei o cenario da PRM039 parada de 7 a 8 de abril ele corrigiu o gantt mas prejudicou o OTD. Quando de seguida dei a condicao de MAX OTD, ele 'esqueceu' a condicao dos 2 dias da PRM39 parada mas ainda aparecia como condicao ativa."

### O que esta a acontecer — passo a passo detalhado

#### Passo 1: O Luis simula "PRM039 parada dias 7-8"

1. O Luis vai ao Simulador, adiciona uma mutacao `machine_down` para PRM039, dias 7-8
2. Clica "Simular" → frontend envia pedido ao backend
3. **No backend**, a funcao `simulate()` faz o seguinte:
   - Cria uma COPIA PROFUNDA dos dados da fabrica (`engine_data`)
   - Na copia, marca PRM039 como bloqueada nos dias 7 e 8
   - Corre o scheduler sobre a copia → gera novo Gantt sem PRM039 nesses dias
   - **Os dados originais NAO sao tocados** — a simulacao so existe na copia
4. O resultado mostra: OTD caiu (porque perdemos 2 dias de capacidade na PRM039)

#### Passo 2: O Luis clica "Aplicar no Gantt"

1. Frontend envia `POST /api/data/simulate-apply`
2. **No backend:**
   - Guarda um snapshot do schedule ATUAL (antes da simulacao) → `state.saved_schedule`
   - Volta a correr a simulacao (outra copia dos dados originais + mutacao)
   - Substitui o schedule ativo pelos resultados da simulacao
   - **MAS os dados da fabrica (`state.engine_data`) continuam INALTERADOS** — sem paragem marcada
3. **No frontend:**
   - Marca `isSimulated = true`
   - Mostra banner laranja: "Cenario simulado: Maquina PRM039 parada dias 1-2"
   - Mostra botao "Reverter"

**Neste ponto, o estado e:**
- Dados da fabrica: ORIGINAIS (sem paragem)
- Schedule ativo: SIMULADO (com paragem)
- Snapshot guardado: schedule ORIGINAL (sem paragem)
- UI: mostra "simulacao ativa"

#### Passo 3: O Luis aplica preset "MAX OTD" (AQUI ESTA O BUG)

1. O Luis vai a Configuracao → Parametros → clica "Max OTD"
2. **No backend:**
   - Preset altera parametros: `jit_enabled=True, jit_threshold=80, safety_buffer=3, urgency_threshold=3`
   - Depois, recalcula o schedule: **`optimize(state.engine_data, ...)`**
   - **PROBLEMA:** `state.engine_data` sao os dados ORIGINAIS — sem paragem da PRM039!
   - O novo schedule e calculado como se a PRM039 estivesse operacional nos dias 7-8
   - Este schedule substitui o anterior (que tinha a paragem)
3. **No frontend:**
   - `refreshAll()` recarrega segments, score, config do backend
   - **MAS NAO LIMPA `isSimulated`** — esta flag continua `true`
   - **MAS NAO VERIFICA se a simulacao ainda esta ativa**
   - O banner laranja continua: "Cenario simulado: Maquina PRM039 parada"
   - O botao "Reverter" continua visivel

**Resultado final:**
- O Gantt mostra um schedule SEM paragem (recalculado pelo preset)
- A UI diz que a simulacao esta ativa (MENTIRA)
- Se o Luis clicar "Reverter", volta ao schedule ANTES da simulacao (que tambem nao tem paragem)
- **A paragem da PRM039 desapareceu completamente**

### Porque e que isto acontece — causa raiz tecnica

O problema tem TRES causas:

**1. As mutacoes da simulacao nao sao guardadas permanentemente**

Quando o Luis clica "Aplicar no Gantt", o backend guarda apenas o schedule resultante (segments, lots, score). NAO guarda as mutacoes que o geraram (`machine_down PRM039 dias 7-8`). Quando outro processo (preset) recalcula o schedule, nao sabe que devia re-aplicar essas mutacoes.

Analogia: e como se tirasses uma fotocopia de um documento com anotacoes a lapis, mas depois apagasses as anotacoes do original. Se alguem te pedir para refazer a fotocopia, sai sem anotacoes.

**2. O preset recalcula sobre os dados originais**

A funcao `apply_preset_endpoint` chama `update_config()` que faz `optimize(state.engine_data, ...)`. O `state.engine_data` e SEMPRE o original — nunca foi modificado pela simulacao. Cada simulacao cria uma copia temporaria que e descartada depois de gerar o schedule.

**3. O frontend nao sincroniza o estado de simulacao**

Quando o `refreshAll()` recarrega dados do backend, nao verifica se a simulacao ainda esta ativa. A flag `isSimulated` so e limpa quando o user clica "Reverter" explicitamente.

### Solucao proposta

**Quando um preset e aplicado durante uma simulacao ativa, limpar a simulacao:**

No backend:
1. Na funcao `apply_preset_endpoint`: verificar se existe `state.saved_schedule`
2. Se sim: limpar o snapshot (`state.saved_schedule = None`)
3. Retornar `simulation_cleared: true` na resposta

No frontend:
1. Na funcao `handlePreset`: apos aplicar, verificar se resposta tem `simulation_cleared`
2. Se sim: limpar `isSimulated`, `simulationSummary`, `canRevert`
3. Adicionalmente: `refreshAll()` deve chamar `/api/data/can-revert` e sincronizar o estado

**Alternativa (mais complexa mas mais poderosa):**
Guardar as mutacoes ativas no backend (`state.active_mutations`). Quando preset recalcula, re-aplicar as mutacoes automaticamente. Isto permitiria "preset + simulacao" em simultaneo. Mas e mais arriscado e complexo.

**Recomendacao:** Opcao simples — preset limpa simulacao. O user pode sempre re-simular depois. E mais previsivel e menos propenso a erros.

### O que o Luis descreveu como workaround
> "So consegui dar a volta a este problema quando primeiro defini MAX OTD e depois pedi a paragem dos 2 dias"

Isto funciona porque:
1. MAX OTD e aplicado sobre dados limpos → schedule sem simulacao
2. Depois, a simulacao e feita SOBRE o schedule com parametros MAX OTD
3. Nao ha conflito porque a simulacao e sempre a ultima operacao

Este workaround confirma o bug: a ordem das operacoes nao devia importar, mas importa.

---

## 3. Presets Sem Indicacao de Ativo {#3-presets-visual}

### O que o Luis reportou
> "Nos presets o 'urgente' o que significa? Nao consigo perceber se eles estao ou nao selecionados. Por exemplo: aparecer a cor quando esta ativo."

### O que esta a acontecer

Os 4 botoes de preset sao visualmente identicos — todos tem fundo com cor a 18% de opacidade e borda fina. Quando o user clica num preset, aparece uma mensagem temporaria "Preset 'X' aplicado (N parametros)" que desaparece apos alguns segundos. Nao ha indicacao permanente de qual preset esta ativo.

### O que cada preset FAZ

Cada preset altera parametros do scheduler. Aqui esta o que cada um faz em detalhe:

**URGENTE (vermelho):**
```
jit_enabled: false         → Desliga o Just-In-Time (producao o mais cedo possivel)
urgency_threshold: 2       → Considera urgente qualquer encomenda a 2 dias do deadline
interleave_enabled: true   → Permite quebrar campanhas para inserir urgentes
lst_safety_buffer: 0       → Zero dias de margem de seguranca
```
**Efeito pratico:** Produz tudo o mais cedo possivel, sem buffer. Bom quando ha muitas encomendas atrasadas. Pior para earliness (stock intermedio alto).

**EQUILIBRADO (azul):**
```
{} → Nao muda nada (reset para defaults do factory.yaml)
```
**Efeito pratico:** Volta aos parametros base da fabrica. E o "normal".

**MIN SETUPS (laranja):**
```
campaign_window: 30        → Janela de 30 dias para agrupar mesma ferramenta
max_edd_gap: 15            → So parte runs se gap entre deadlines > 15 dias
edd_swap_tolerance: 10     → Tolerancia de 10 dias para re-ordenar dentro de campanha
```
**Efeito pratico:** Agrupa ao maximo producoes da mesma ferramenta. Menos setups = menos tempo perdido. Pode prejudicar OTD se encomendas urgentes ficam para tras.

**MAX OTD (verde):**
```
jit_enabled: true          → Liga Just-In-Time (produz o mais tarde possivel)
jit_threshold: 80.0        → Aplica JIT mesmo com OTD a 80%
lst_safety_buffer: 3       → 3 dias de margem de seguranca
urgency_threshold: 3       → Considera urgente qualquer encomenda a 3 dias
```
**Efeito pratico:** Maximiza entregas a tempo. JIT atrasa producao para reduzir stock mas garante que esta la quando precisa. Bom para OTD-D (entrega diaria).

### Solucao proposta

1. Guardar qual preset foi o ultimo aplicado (no frontend ou backend)
2. Mostrar o botao ativo com visual diferente: fundo mais opaco (40% vs 18%), borda mais grossa (2px vs 0.5px), possivel icone de check
3. Se o user editar parametros manualmente, desmarcar o preset (ja nao e "puro")

---

## 4. BFP114 Nao Antecipada Quando Ha Espaco {#4-bfp114}

### O que o Luis reportou
> "Qual e o raciocinio para, no caso da imagem 2, ele nao antecipar a producao da BFP114 quando tem espaco para isso?"

### O que esta a acontecer — explicacao completa do scheduler

O scheduler da Incompol funciona em 5 fases sequenciais. Para entender porque BFP114 nao e antecipada, preciso de explicar como funciona a atribuicao de maquinas:

#### Fase 1: Dimensionamento de Lotes
Os pedidos do ISOP sao convertidos em lotes de producao. Cada lote tem uma quantidade (arredondada ao eco-lot) e um deadline (EDD).

#### Fase 2: Agrupamento por Ferramenta
Lotes da mesma ferramenta e maquina sao agrupados em "ToolRuns" (corridas de ferramenta). Um ToolRun e: "montar ferramenta X na maquina Y, produzir lotes A, B, C, desmontar". Isto minimiza setups.

#### Fase 3: Despacho (onde o "problema" acontece)

**Fase 3.1 — Atribuicao de maquina:**
Cada ToolRun e atribuido a UMA maquina. Esta decisao e feita UMA VEZ e e PERMANENTE — o run NUNCA muda de maquina depois disto.

A logica e simples:
- Se a ferramenta so pode ir para uma maquina → vai para essa (locked)
- Se tem maquina alternativa → compara a carga das duas e vai para a menos carregada

**Esta decisao e feita ANTES do scheduling propriamente dito.** Nao considera gaps futuros, so a carga total.

**Fase 3.2 — Sequenciacao:**
Dentro de cada maquina, os runs sao ordenados por deadline (EDD). Depois ha logica de campanha (agrupar ferramentas iguais) e interleave (inserir urgentes).

**Fase 3.3 — Alocacao:**
Os runs sao processados sequencialmente, maquina a maquina. Cada maquina trabalha na sua fila sem "olhar" para as outras. **NAO existe logica de "preencher buracos"** — se uma maquina tem tempo livre e outra esta sobrecarregada, nao ha transferencia.

#### Fase 4: JIT (Just-In-Time)
Se JIT esta ativo (e esta, por default), o scheduler ATRASA a producao deliberadamente. Calcula o "Latest Start Time" (ultimo dia possivel para comecar sem atrasar) e empurra os runs para esse dia.

**Isto significa que mesmo que haja espaco livre na segunda-feira, o scheduler pode colocar BFP114 na quinta — de proposito — porque so precisa de estar pronta na sexta.**

#### Porque BFP114 especificamente nao antecipa

Olhando para a imagem 2 que o Luis marcou:
- PRM039 tem BFP079 a correr continuamente ate dia 15 (quarta-feira)
- BFP114 aparece dia 16 (quinta-feira) — depois de BFP079 acabar
- Ha espaco antes (o Luis viu isto e marcou com seta)

Possiveis razoes (todas relacionadas com o design do scheduler):

1. **BFP114 esta atribuida a PRM039** (mesma maquina que BFP079). Como BFP079 esta a frente na fila (EDD mais cedo), BFP114 tem de esperar. Nao pode "saltar" para outra maquina.

2. **JIT esta a atrasar BFP114**. Se o EDD de BFP114 e dia 18 e a producao demora 2 dias, o JIT coloca-a no dia 16 (ultimo dia possivel). Mesmo que houvesse espaco no dia 13.

3. **Tool contention**: A ferramenta BFP114 pode estar montada noutra maquina ate dia 15. Cada ferramenta so pode estar num sitio de cada vez.

4. **Crew serialization**: Ha uma unica equipa de setup que serve todas as maquinas. Se a equipa esta ocupada a montar/desmontar noutras maquinas, BFP114 tem de esperar.

### E isto e um bug?

**NAO.** E comportamento esperado do scheduler com JIT ativo. A filosofia e: "produzir o mais tarde possivel sem atrasar" (lean manufacturing). Produzir cedo gera stock intermedio que custa dinheiro e espaco.

### O que o user pode fazer

Se quiser antecipar producao:
- **Preset "Urgente"**: desliga JIT → tudo e antecipado
- **Desligar JIT manualmente**: em Parametros, colocar "JIT Activo" = false
- **Reduzir LST Safety Buffer**: de 2 para 0 — producao comeca ainda mais tarde (ou cedo, depende)

---

## 5. SKU no Gantt em Vez de Ferramenta {#5-sku-gantt}

### O que o Luis reportou
> "Importante no gantt trocar o numero da ferramenta pela referencia. E mais facil para ler o gantt."

### O que esta a acontecer

Os blocos do Gantt mostram o ID da ferramenta (ex: "BFP082", "BFP114", "JDE002"). Sao codigos internos que identificam o molde/ferramenta fisica. O Luis quer ver o SKU (referencia do artigo/peca que esta a ser produzida).

No codigo do Gantt, existem dois pontos onde o label e escrito:
- **Bloco grande** (vista de dia ou zoom alto): mostra `tool_id` em bold, seguido de SKU + quantidade na segunda linha
- **Bloco pequeno** (vista de semana ou zoom baixo): mostra apenas `tool_id`

O campo `sku` JA EXISTE em cada segmento — simplesmente nao e usado como label principal.

### Questao pratica

O tool_id tem 6 caracteres (ex: "BFP082"). O SKU pode ter 10-15 caracteres (ex: "1064169X100"). Em blocos pequenos (< 60 pixels de largura), o SKU nao cabe. Opcoes:
- Blocos grandes: mostrar SKU completo
- Blocos pequenos: mostrar SKU truncado (primeiros 8 chars) ou manter tool_id
- Tooltip: mostrar informacao completa ao passar o rato

### Solucao

Substituir `s.tool_id` por `s.sku` nos labels dos blocos, com logica de tamanho:
- Se o bloco tem mais de 60px: mostrar SKU
- Se tem menos de 60px: mostrar tool_id (mais curto, cabe)
- Manter tool_id como informacao secundaria ou tooltip

Alteracao muito simples — 2 linhas de codigo.

---

## 6. BFP202 Repeticao Desnecessaria {#6-bfp202}

### O que o Luis reportou
> "Na imagem 3 observo uma repeticao desnecessaria da producao da ferramenta BFP202 mas quando alterei a configuracao para Min Setups e MAX OTD ele corrigiu, mas nao sei qual preset esta selecionado."

### O que esta a acontecer

Na imagem 3, PRM043 mostra BFP202 em 3 blocos consecutivos. Isto significa 3 "corridas" separadas da mesma ferramenta — potencialmente com setup entre elas (montar, produzir, desmontar, montar outra vez, produzir, etc.).

### Porque e que isto acontece

O scheduler tem um mecanismo de "split" que parte corridas longas:

**Regras de split (tool_grouping.py):**
1. Se o gap entre deadlines consecutivos > 10 dias → partir
2. Se o span total > 30 dias → partir
3. Se o tempo cumulativo > 5 dias de capacidade (5100 minutos) → partir

Se BFP202 tem 3 encomendas com deadlines espacados (ex: dia 5, dia 16, dia 28), o gap entre dia 5 e dia 16 e 11 (> 10) → cria 2 runs separados. Depois pode haver um terceiro split por span ou capacidade.

Depois, o sequenciador tenta re-agrupar com "campaign sequencing" (janela de 15 dias por default). Mas se ha outros runs no meio (outra ferramenta com EDD entre dia 5 e dia 16), a re-agrupacao pode falhar.

### Porque "Min Setups" corrige

O preset "Min Setups" muda tres parametros:
- `max_edd_gap: 15` (em vez de 10) → menos splits
- `campaign_window: 30` (em vez de 15) → re-agrupamento mais agressivo
- `edd_swap_tolerance: 10` (em vez de 5) → mais liberdade para re-ordenar

Com estes parametros, BFP202 fica num unico ToolRun ou em runs consecutivos sem setup entre eles.

### Este ponto esta ligado ao Ponto 3

O Luis conseguiu corrigir com "Min Setups + Max OTD" mas nao sabe qual preset esta ativo. Se tivesse indicacao visual (Ponto 3), saberia que a configuracao atual resolve o problema.

### Nao requer alteracao de codigo do scheduler

A logica funciona como desenhada. Os presets servem exatamente para este tipo de ajuste.

---

## 7. Lead Times — BFP178 e BFP186 {#7-lead-times}

### O que o Luis reportou
> "Nas ferramentas BFP178 e BFP186, as referencias tem prazos de fabrico muito elevados, o sistema esta a ter isso em consideracao?"

### Resposta curta: NAO

A coluna F do ISOP ("Prz.Fabrico") e EXPLICITAMENTE ignorada pelo sistema. Isto esta documentado na especificacao do projeto (CLAUDE.md): "IGNORAR SEMPRE: F(Prz.Fabrico) e K(STOCK-A)".

### O que e "Prz.Fabrico"?

"Prazo de Fabrico" e o tempo estimado entre o inicio da producao e a peca estar pronta para entrega. Inclui:
- Tempo de setup (montar ferramenta)
- Tempo de producao (estampar pecas)
- Tempo de acabamento/qualidade (se aplicavel)
- Possivel tempo de logistica interna

Para BFP178 e BFP186, se o prazo de fabrico e "muito elevado" (ex: 10-15 dias), significa que a producao destas pecas demora significativamente mais que a media.

### O que o sistema USA para calcular prazos

Em vez de usar "Prz.Fabrico", o sistema calcula o tempo de producao diretamente:

```
tempo_producao = quantidade / (pecas_por_hora × OEE)
```

Onde:
- `quantidade` = numero de pecas da encomenda (do NP)
- `pecas_por_hora` (pH) = cadencia da maquina para esta ferramenta (do ISOP)
- `OEE` = eficiencia global do equipamento (0.66 = 66%)

O deadline (EDD) vem da coluna de datas do ISOP: se NP=-15600 na coluna do dia 10, o EDD e o dia 10.

**NAO ha ajuste do EDD baseado no lead time.** O sistema assume que o EDD ja e o dia em que tem de estar pronto.

### BFP178 e BFP186 em detalhe

| Propriedade | BFP178 | BFP186 |
|-------------|--------|--------|
| Maquina primaria | PRM039 | PRM039 |
| Maquina alternativa | PRM043 | PRM031 |
| Setup | 0.5 horas (30 min) | 0.5 horas (30 min) |
| Twin (pecas gemeas) | Sim — 2 SKUs simultaneos | Sim — 2 SKUs simultaneos |
| Tratamento especial | Nenhum | Nenhum |

Ambas partilham PRM039 como maquina primaria — que tambem serve BFP079, BFP080, BFP114, BFP183, etc. Isto cria contencao: muitas ferramentas a competir pela mesma maquina.

### Impacto de ignorar o prazo de fabrico

**Cenario hipotetico:** Se BFP178 tem prazo de fabrico de 10 dias e o sistema ignora:
- Encomenda: 5000 pecas, deadline dia 15
- O scheduler pode comecar a produzir no dia 13 (JIT empurra para tarde)
- Se a producao demora 3 dias (dia 13, 14, 15) → acaba no dia 15
- MAS se o prazo de fabrico real e 10 dias (dia 5 → dia 15), devia ter comecado no dia 5
- O scheduler "nao sabe" que devia comecar mais cedo

**CONTUDO:** O tempo de producao calculado pelo scheduler (`qty / (pH × OEE)`) ja deveria capturar a duracao real. Se a cadencia (pH) esta correta no ISOP, o tempo de producao calculado = tempo real.

O "Prz.Fabrico" e provavelmente redundante se o pH esta correto. A diferenca seria se o prazo incluir tempos que o scheduler nao modela: acabamento, qualidade, secagem, transporte interno, etc.

### Pergunta critica para o Luis

**Os EDDs no ISOP ja incluem o prazo de fabrico?**

Ou seja: quando o ERP gera o ISOP, a data da coluna de datas e:
- (A) A data em que o cliente quer receber? → O scheduler devia descontar o lead time
- (B) A data em que a producao tem de estar concluida? → O scheduler esta correto

Se a resposta e (A), precisamos de subtrair o prazo de fabrico ao EDD para que o scheduler comece a produzir com antecedencia suficiente.

### Solucao possivel (se necessario)

Se o Luis confirmar que os EDDs NAO incluem lead time:

1. Adicionar campo `lead_time_days` a configuracao de ferramentas no YAML
2. No lot_sizing.py, ajustar: `edd_adjusted = edd - lead_time_days`
3. Assim BFP178 com lead_time=10 e EDD=15 teria EDD ajustado=5 → scheduler comeca dia 5

Ou, mais simples:
- Aumentar `LST_SAFETY_BUFFER` de 2 para 5 dias (global, afeta todas as ferramentas)
- Menos preciso mas sem configuracao per-tool

---

## Resumo Executivo

| # | Problema | Gravidade | Tipo | Solucao |
|---|----------|-----------|------|---------|
| 1 | Tema dark | Media | Visual | Redefinir palette para light |
| 2 | Preset esquece simulacao | **CRITICA** | Bug | Limpar simulacao ao aplicar preset + sync frontend |
| 3 | Preset sem indicador | Alta | UX | Guardar estado + visual destacado |
| 4 | BFP114 nao antecipada | Baixa | Design | Comportamento esperado (JIT). Explicar. |
| 5 | SKU no Gantt | Media | Visual | Substituir tool_id por sku (2 linhas) |
| 6 | BFP202 repeticao | Baixa | Config | Resolvido por preset "Min Setups" |
| 7 | Lead times | **A clarificar** | Logica | Perguntar se EDDs incluem lead time |

### Pontos que precisam de codigo (1, 2, 3, 5)
### Pontos que precisam de explicacao ao Luis (4, 6)
### Pontos que precisam de esclarecimento do Luis (7)

---

## Estado Final (resolucao)

| # | Problema | Estado | Resolucao |
|---|----------|--------|-----------|
| 1 | Tema dark | **IMPLEMENTADO** | Tema light no commit `dac02f3` |
| 2 | Preset esquece simulacao | **IMPLEMENTADO** | Bug corrigido no commit `dac02f3` |
| 3 | Preset sem indicador | **IMPLEMENTADO** | Indicacao visual de preset activo no commit `dac02f3` |
| 4 | BFP114 nao antecipada | **FECHADO** | Comportamento esperado (JIT) — sem alteracao de codigo |
| 5 | SKU no Gantt | **IMPLEMENTADO** | Labels SKU no Gantt no commit `dac02f3` |
| 6 | BFP202 repeticao | **FECHADO** | Comportamento esperado (regras de split) — sem alteracao de codigo |
| 7 | Lead times BFP178/BFP186 | **FECHADO** | EDDs do ISOP ja sao data de producao concluida — scheduler correcto |

### Itens 1, 2, 3, 5 — Implementados

Resolvidos no commit `dac02f3` ("feat: light theme, preset UX, SKU labels, simulation bug fix"):

- **1 — Tema light:** A palette foi redefinida para fundo claro, conforme pedido pelo Luis.
- **2 — Bug preset esquece simulacao:** O bug critico foi corrigido — aplicar um preset durante uma simulacao activa limpa o estado de simulacao e sincroniza a UI, eliminando o estado inconsistente descrito.
- **3 — Presets indicacao visual:** Os presets passam a ter indicacao visual do preset activo.
- **5 — SKU no Gantt:** Os blocos do Gantt passam a mostrar o SKU em vez do ID da ferramenta.

### Itens 4 e 6 — Comportamento esperado (sem alteracao de codigo)

- **4 — BFP114 nao antecipada:** Comportamento esperado do scheduler com JIT activo. O JIT produz o mais tarde possivel para reduzir stock intermedio. Nao e um bug. Se for preciso antecipar, usar o preset "Urgente" ou desligar o JIT. A explicar ao Luis.
- **6 — BFP202 repeticao:** Comportamento esperado das regras de split (gap entre EDDs, span, capacidade cumulativa). O preset "Min Setups" reagrupa as corridas, como desenhado. Nao requer alteracao de codigo. A explicar ao Luis.

### Item 7 — Lead times BFP178/BFP186 — FECHADO

O Luis confirmou que os EDDs do ISOP **ja sao a data de producao concluida** (resposta (B) da pergunta critica acima), e nao a data em que o cliente quer receber. Logo:

- O scheduler esta correcto — o EDD ja e o dia em que a peca tem de estar pronta.
- A coluna F (Prz.Fabrico) continua a ser ignorada, conforme especificado no CLAUDE.md.
- Nao e preciso alterar codigo nem adicionar `lead_time_days`.
