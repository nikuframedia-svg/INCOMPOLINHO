# Pesquisa algorítmica aplicada ao INCOMPOLINHO

02/10/2026. Investigação feita com a skill Exa Search: **10 pesquisas, 61
resultados devolvidos, 58 URLs distintas**, em quatro frentes. Foram lidos os
trechos relevantes de 13 páginas/documentos centrais e consultados três ficheiros
oficiais da versão 9.15 do OR-Tools. Dois destes repetem documentos antes lidos
pela branch `stable`; a lista abaixo consolida 14 fontes centrais.

Não significa 61 artigos lidos integralmente. Foram excluídos tutoriais sem
fonte primária, páginas agregadoras quando existia o original e soluções de
problemas incompatíveis. Para páginas muito longas leram-se os trechos
disponíveis; o artigo de Weng et al. foi avaliado pelo resumo público, sem
acesso ao texto integral. Não foram enviados à pesquisa os dados da fábrica.

## 1. Pergunta concreta e método

Como produzir cedo, respeitando uma libertação de material de cinco dias úteis,
cinco prensas com velocidades diferentes, ferramentas partilhadas, setups,
equipas/operadores por turno, gémeas e produção protegida, usando pouco compute?

Critérios de escolha: fidelidade das restrições; qualidade da primeira solução;
melhoria sob orçamento; memória/CPU; conservação do melhor candidato;
explicabilidade; esforço de integração no código existente. Não ordenar técnicas
por resultados de makespan em benchmarks que não incluem estas condições.

| Frente | Pesquisas | Resultados | Questão investigada |
|---|---:|---:|---|
| Modelo industrial e recursos | 3 | 21 | Máquinas paralelas/FJSP, setups, ferramentas, operadores e calendários |
| Heurísticas e propriedades | 2 | 12 | Geração serial, planos ativos, shifting bottleneck |
| CP-SAT e controlo de execução | 3 | 18 | Modelação, objetivos, hints, workers, timeout e estados |
| Alternativas e explicações | 2 | 10 | PyJobShop, falhas de viabilidade e explicações contrastivas |

## 2. Classificar corretamente o problema

O ISOP alimenta operações independentes de prensa, posteriormente dimensionadas
em lotes/campanhas, com alternativas, recurso ferramenta e outputs gémeos. A
subcontratação introduz datas e lead externo. Neste percurso não existe evidência
de um grafo geral de operações sucessivas por OF como num job shop clássico.

A família mais próxima é **unrelated parallel machine scheduling com recursos
secundários e setups**, enriquecida pelas regras do projeto. “Unrelated” indica
que a duração depende da máquina escolhida; não significa que as máquinas não
partilham ferramentas ou trabalhadores. A literatura de FJSP serve para técnicas
de procura, não como modelo pronto a copiar.

A janela é um limite de libertação. Já a antecipação é um objetivo. Um modelo
que minimiza earliness por defeito faz o contrário do pedido, mesmo respeitando
todas as máquinas. Um modelo que minimiza só makespan pode deixar um lote
desnecessariamente tarde sem alterar o fim do último trabalho.

## 3. Fontes centrais e consequências

| ID | Fonte primária | O que sustenta | Aplicação e limite |
|---|---|---|---|
| S1 | [Kolisch — Serial and parallel resource-constrained project scheduling methods revisited](https://www.econstor.eu/bitstream/10419/155418/1/manuskript_344.pdf) | Construção serial/paralela por prioridades e propriedades de planos ativos/não atrasados no RCPSP | Base para inserção rápida. As garantias do RCPSP clássico não cobrem automaticamente setups, gémeas e alternativas Incompol |
| S2 | [Heinz et al. — Constraint Programming and Constructive Heuristics for Parallel Machine Scheduling with Sequence-Dependent Setups and Common Servers](https://arxiv.org/html/2305.19888) | Heurística construtiva usada como solução inicial de CP para máquinas e servidores de setup | Correspondência forte com equipas de preparação. O artigo usa máquinas idênticas e makespan; não prova desempenho no nosso modelo |
| S3 | [Exact and metaheuristic approaches for unrelated parallel machine scheduling](https://link.springer.com/article/10.1007/s10951-021-00714-6) | Durações por máquina, elegibilidade, setups e objetivos lexicográficos de atraso/makespan; métodos exatos e simulated annealing | Ajuda a escolher vizinhanças e separar objetivos; não substitui material, gémeas e serviço por encomenda |
| S4 | [Yepes-Borrero et al. — Unrelated parallel machine scheduling problem with setup times and additional resources](https://link.springer.com/article/10.1007/s10479-026-07065-5) | Recursos limitados durante setups e tratamento de inviabilidades desses recursos | Confirma que disponibilidade da prensa sozinha é insuficiente. Resultados relativos de benchmark não estimam o nosso tempo de resposta |
| S5 | [Weng, Lu e Ren — Unrelated parallel machine scheduling with setup consideration and a total weighted completion time objective](https://www.sciencedirect.com/science/article/abs/pii/S0925527300000669) | Heurísticas para jobs independentes, setups e conclusão ponderada | Objetivo temporal mais próximo que makespan; conclusão média não equivale a primeiro início de cada lote. Apenas resumo público |
| S6 | [OR-Tools 9.15 — Scheduling recipes](https://github.com/google/or-tools/blob/v9.15/ortools/sat/docs/scheduling.md) | Intervalos, opcionais, `NoOverlap`, `Cumulative`, capacidade variável e transições por sucessores | Componentes necessários ao modelo local. Um exemplo de transições não modela sozinho todos os recursos de preparação |
| S7 | [OR-Tools 9.15 — sat_parameters.proto](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto) | Workers, tempo real/determinístico, limites e tolerâncias | Especificar recursos de execução e medir; não interpretar todos os parâmetros como garantias operacionais |
| S8 | [OR-Tools 9.15 — cp_model.proto](https://github.com/google/or-tools/blob/v9.15/ortools/sat/cp_model.proto) | Hints e assumptions; núcleo suficiente para inviabilidade | Hint é tentativa de ajuda, não incumbent garantido. Núcleo suficiente não é necessariamente mínimo |
| S9 | [Google — CP-SAT Solver](https://developers.google.com/optimization/cp/cp_solver) | Estados `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `MODEL_INVALID`, `UNKNOWN` | A interface e o relatório têm de conservar estas distinções, incluindo o âmbito do modelo |
| S10 | [Prud'homme, Lorca e Jussien — Explanation-Based Large Neighborhood Search](https://hal.science/hal-01087844v1/document) | LNS relaxa subconjuntos; conflitos/explicações podem orientar a vizinhança | Justifica libertar trabalhos acoplados. O primeiro passo pode usar conflitos de recursos sem implementar todo o mecanismo do artigo |
| S11 | [Li et al. — Learning-Guided Rolling Horizon Optimization for Long-Horizon Flexible Job-Shop Scheduling](https://arxiv.org/html/2502.15791) | Janelas sobrepostas e custo de reotimizar decisões repetidas | Aproveitar a ideia de decomposição/cache se necessário; não adotar a componente neural sem dados, treino e ganho medido |
| S12 | [PyJobShop — Resource breaks](https://pyjobshop.org/stable/examples/breaks.html) | Pausas e tarefas que podem continuar após uma pausa | Referência útil para calendários. Pausa de turno não é troca arbitrária de molde; os significados precisam de ser preservados |
| S13 | [PyJobShop — Objectives](https://pyjobshop.org/stable/examples/objectives.html) | Diferentes objetivos temporais e somas ponderadas | Permite comparação, mas trocar de API não define a política Incompol nem garante lexicografia estrita |
| S14 | [Lauffer e Topcu — Human-Understandable Explanations of Infeasibility for Resource-Constrained Scheduling Problems](https://niklaslauffer.github.io/files/explain2019.pdf) | Explicações por subconjuntos de restrições e possíveis relaxações | Orienta “porquê aqui e não ali”. Não justifica chamar impossível a uma pesquisa interrompida |

Todas as fontes centrais são documentação dos autores do software, artigos
originais ou versões depositadas por investigadores/instituições. A evidência
mais forte para a falha atual continua a ser a reprodução no snapshot, não a
existência de uma técnica com bons resultados noutra fábrica.

### 3.1 Resultados que não se devem generalizar

S2 reporta instâncias até 20 máquinas/500 tarefas em dez segundos e distância
média de cerca de 5% ao limite inferior no contexto estudado. Isto apoia a
plausibilidade de uma abordagem híbrida rápida, **não** um SLA ou garantia de
qualidade de INCOMPOLINHO. Máquina idêntica, objetivo, dados, solver e hardware
diferem. Não transpor esses números para o plano de produção.

S3 mostra a utilidade de metaheurísticas em instâncias grandes e de métodos
exatos em instâncias pequenas. A nossa recomendação de CP-SAT local é uma
inferência de engenharia combinando essa literatura, S10, a infraestrutura
existente e o contraexemplo reproduzido; nenhum artigo testou este repositório.

S11 usa aprendizagem para acelerar rolling horizon. As percentagens reportadas
não sustentam introduzir redes neurais neste projeto. Primeiro eliminar pesquisa
redundante e medir o benefício de janelas sem componente aprendida.

## 4. Comparação das opções

| Método | Vantagem neste caso | Limite/custo | Decisão |
|---|---|---|---|
| Regras EDD/urgência + inserção por eventos | Primeira solução barata, fácil de explicar e medir | Ganância local; pode bloquear outra campanha | Base construtiva e N0/N1 |
| VND/VNS com inserção/troca/transferência | Reutiliza os movimentos e validadores existentes | Precisa de comparador único e vizinhanças suficientes | Primeira camada de melhoria |
| CP-SAT com LNS dirigida a conflitos | Trata recursos acoplados, fronteiras e alternativas num grupo pequeno | Construção do modelo e estado retido têm custo; limite local não é global | Segunda camada recomendada |
| CP-SAT global com orçamento curto | Modelo unificado e bounds, infraestrutura existente | Pode gastar tempo em entrega/viabilidade e não chegar à antecipação | Manter para construção/diagnóstico e benchmark; não única via de antecipação |
| CP-SAT global longo/exato | Pode provar ótimo/inviabilidade para o modelo quando termina | Custo imprevisível para interatividade; prova só do modelo representado | Oráculo pequeno ou análise offline |
| Simulated annealing/tabu/ILS | Explora sequências que exigem movimentos intermédios piores | Mais parâmetros/aleatoriedade; ainda exige reconstrução e validação | Challenger de benchmark se VND+LNS não chegar |
| Shifting bottleneck | Concentra-se no recurso limitante | Formulação clássica de job shop/makespan; ferramentas e equipas acoplam máquinas | Usar a ideia de selecionar gargalos, não transplantar o algoritmo |
| GA/MAP-Elites/surrogate | Exploração offline de parâmetros | Muitas avaliações, tuning e manutenção; não corrige contrato errado | Retirar do caminho mental operacional; preservar experiências só se usadas |
| Rolling horizon | Reduz subproblemas em horizontes grandes | Fronteiras, sobreposição e procura posterior podem criar miopia | Só depois de medir necessidade; não confundir com os cinco dias de material |
| Migrar para PyJobShop | Interface clara e exemplos úteis | Reimplementar gémeas, proteção, serviço por cliente e persistência; migração não resolve objetivos | Referência e eventual protótipo comparativo, sem migração inicial |
| RL/otimização aprendida | Possível política rápida após treino | Dados/treino/distribution shift e falta de prova de regras | Sem justificação nesta fase |

O facto de o problema ser combinatório não transforma uma lacuna de geração
em falta inevitável de compute. A inserção BFP186 foi encontrada em menos de
dois segundos no âmbito auditado. Primeiro corrigir o que o algoritmo procura
e o que aceita; só depois comparar motores ou aumentar recursos.

## 5. Desenho sugerido e armadilhas

### 5.1 Recursos e tempo

Um setup pode exigir simultaneamente máquina, molde e equipa; produção exige
máquina, molde e operadores. O trabalho pode continuar após um fecho, mas a
montagem precisa de estado válido. Um `NoOverlap` só sobre produção ou apenas
um custo de troca não cobre esse comportamento.

É necessário distinguir tempo civil e produtivo. Compressão do calendário deve
ter conversões reversíveis e perfis por recurso. Uma indisponibilidade parcial
não pode ser arredondada para o dia inteiro; um turno extra não cria capacidade
de operadores por inferência. Esta exigência vem do código e dos requisitos
observados; é mais específica do que os exemplos bibliográficos.

### 5.2 Objetivo e serviço

Usar lexicografia explícita, não pesos arbitrários como “atraso ×1000 menos
setup” sem demonstrar que o peso domina todas as outras parcelas. Manter a
verificação final por encomenda mesmo que o solver use uma aproximação local.
Nunca chamar a um score de makespan, earliness médio ou duração ponderada
“primeiro início possível” sem correspondência matemática.

No plano proposto, a ordem entre lotes concorrentes torna explícito quem pode
ocupar primeiro o recurso. Nem todos os lotes podem ter simultaneamente o seu
início mínimo isolado. Uma biblioteca não escolhe esta regra pelo negócio.

### 5.3 Baixo compute e terminação

S7 confirma que um worker desliga o paralelismo do solver, e que tempo
determinístico é uma medida interna relacionada com esforço, não o relógio
da fábrica. Usar ambos os limites adequadamente. O comentário de
`max_memory_in_mb` restringe a sua aplicação ao SAT puro; não o apresentar como
proteção completa de memória de CP-SAT. Tolerâncias de gap positivas também
podem levar ao estado `OPTIMAL`; guardar bound/gap e critérios configurados.

Guardar separadamente a última solução validada é uma decisão da aplicação.
S8 avisa que hints nem sempre aceleram e não prometem uma solução próxima.
Interrupção de uma chamada não autoriza descartar o incumbent já aprovado pelo
avaliador. Também não autoriza usar um incumbent de inputs antigos.

### 5.4 Explicações

Responder a uma pergunta de posição testando um contrafactual no mesmo snapshot:
fixar o início pedido; primeiro conservar os restantes lotes; depois libertar
um grupo de conflitos se houver orçamento. Informar início de setup e início de
produção separadamente. Associar resposta à revisão e às restrições verificadas.

S14 fundamenta explicações centradas nos conflitos. Produzir um núcleo mínimo
pode ser caro, e nem todas as restrições globais aceitam reificação direta no
CP-SAT. Começar com evidências de intervalos/recursos; usar assumptions apenas
em formulações que as suportem, sem inventar um núcleo mínimo.

## 6. O que falta medir antes de declarar o método vencedor

1. Comparação atual vs inserção completa N1 vs VND+CP-SAT local nos mesmos
   snapshots, com exatamente o mesmo contrato de negócio.
2. Tempo até primeira solução válida; objetivo final; oportunidades restantes;
   RAM; tempo de modelo, pesquisa e validação; CPU de uma e duas unidades.
3. Instâncias pequenas resolvidas por oráculo independente e instâncias reais
   com ausências, ferramentas bloqueadas, gémeas e histórico.
4. Frio/quente e concorrência de requests; orçamento de fim a fim, incluindo
   aplicação/persistência quando esse percurso for autorizado.
5. Repetições suficientes para percentis; relatório parcial quando a procura
   ou o deadline limita a conclusão.

Não há base para afirmar agora qual algoritmo é globalmente mais rápido ou
ótimo para todos os inputs. Há base concreta para priorizar a correção do
contrato e da geração de antecipações, mantendo CP-SAT para os grupos difíceis.

Ligação ao [plano de implementação](../plano-solver-2026-10-02.md).
