# Carregamento ISOP em segundo plano

O carregamento completo mantém três passos: escolher ficheiro, confirmar o
estado inicial `all_free` e acompanhar o cálculo. Um candidato válido é aplicado
automaticamente. Exceções permitidas exigem motivo e autor; conflitos bloqueantes
nunca podem ser aprovados. As regras e os orçamentos do otimizador mantêm-se.

## API

Todas as respostas abaixo usam `{ "job": LoadJob }`. `LoadJob` contém `id`,
`filename`, `status`, `phase`, `message`, datas, `elapsed_ms`, `timings_ms`,
`base_revision`, `prepared`, `gate_report`, `result` e `error`. Os últimos quatro
conteúdos podem ser `null`. `prepared` conserva `PreparedLoad`; `result` conserva
`LoadResponse` e só existe após a aplicação; `gate_report` conserva `GateReport`.
Os tipos do cliente estão em `frontend/src/api/types.ts`.

| Pedido | Entrada | Resposta |
| --- | --- | --- |
| `POST /api/data/load/prepare` | Multipart: `file`, `request_id` (UUID) | `202`; leitura e validação em segundo plano |
| `POST /api/data/load/confirm` | JSON: `token` = UUID, `expected_revision` = `base_revision`, `mode: "all_free"` | `202`; aceita o cálculo, sem esperar pelo resultado |
| `GET /api/data/load/jobs/{id}` | UUID | `200`; estado atual, validações e comprovativo |
| `POST /api/data/load/jobs/{id}/approve` | JSON: `expected_revision`, `approval_reason`, `approval_author` | `202`; aplica o candidato guardado, sem otimizar novamente |
| `POST /api/data/load/jobs/{id}/cancel` | UUID | `200`; impede aplicação posterior |

O ficheiro deve ser `.xlsx`, não vazio e ter no máximo 25 MB. O modo manual é
rejeitado antes do cálculo. O navegador gera e guarda o UUID **antes** do envio;
clientes externos devem fazer o mesmo. O servidor ainda gera um UUID quando o
campo é omitido, mas esse cliente não consegue recuperar uma resposta de aceitação
perdida sem conhecer o identificador.

Reenviar o mesmo UUID e conteúdo devolve a tarefa existente. Um nome, conteúdo ou
opções de carregamento diferentes com o mesmo UUID produzem `409 different_input`.
Confirmar repetidamente não repete o cálculo. Aprovar novamente após aplicação
devolve o comprovativo. A confirmação e a aprovação usam a revisão original;
não se deve substituir automaticamente a revisão numa tentativa repetida.

Existe um carregamento pendente por instância, incluindo os estados de preparação
e de espera por aprovação. Outro envio recebe `409 load_in_progress`, com
`detail.job_id`; a interface permite acompanhar essa tarefa. Identificadores
desconhecidos devolvem `404 not_found`. Erros usam o formato FastAPI `detail`,
com `code` e `message` nas decisões do gestor.

### Compatibilidade

`POST /api/data/load` usa o mesmo gestor e agora responde `202`, em vez de devolver
diretamente um plano. Aceita multipart `file`/`request_id`, exige os parâmetros
`expected_revision` e `assume_machines_free=true`, e confirma automaticamente após
a preparação. As opções legadas de aprovação continuam sujeitas às validações
completas e à presença de motivo e autor. Todos os clientes devem acompanhar
`GET /load/jobs/{id}`. Frontend e backend devem ser entregues em conjunto.

## Estados e recuperação

| Estado | Significado |
| --- | --- |
| `preparing` | Leitura, transformação e qualidade dos dados |
| `prepared` | Ficheiro pronto; aguarda confirmação |
| `queued` | Cálculo confirmado; aguarda o executor |
| `running` | Cálculo, análises ou aplicação em curso |
| `awaiting_approval` | Candidato calculado com exceções permitidas |
| `applied` | Snapshot e comprovativo persistidos; plano publicado |
| `blocked` | Validações impedem a aplicação |
| `failed` | Falha técnica, ficheiro inválido ou reinício do servidor |
| `cancelled` | Aplicação cancelada; mantém o plano anterior |
| `stale` | Revisão, conjunto de dados ou configuração de origem mudou |

Os cinco últimos estados são terminais. Fechar ou atualizar o navegador não
cancela o cálculo nem a aplicação automática já confirmada. O identificador fica
em `sessionStorage` (`pp1ActiveLoadJobId`) e o acompanhamento é recuperado na mesma
sessão, mesmo quando existe um plano ativo. Uma nova sessão não herda essa chave;
um novo envio encontra a tarefa pendente através de `load_in_progress`.

As consultas normais ocorrem a cada segundo. Falhas de ligação aumentam o
intervalo para dois, quatro e até cinco segundos e mostram “A restabelecer
ligação”. A fase apresentada vem do servidor e não corresponde a uma percentagem
estimada. Se a resposta a um comando se perder, o cliente consulta o mesmo UUID.
Se o envio não for encontrado, pode reenviar o mesmo ficheiro com esse UUID.

Após `applied`, o cliente consulta o plano ativo e atualiza os dados. Se essa
atualização falhar, mostra que o carregamento terminou e permite repetir apenas
as consultas. Não repete a importação. Respostas HTML do proxy, incluindo `524`,
são convertidas em mensagens curtas; erros JSON estruturados mantêm o seu detalhe.
Timeout e falha de rede têm códigos distintos.

## Consistência e reinício

O gestor usa `ThreadPoolExecutor(max_workers=1)`. Leitura, otimização, validações,
análises e serialização trabalham sobre dados separados do plano ativo. O candidato
fica em memória enquanto espera por aprovação. O cancelamento sinaliza o executor
e impede a aplicação imediatamente; uma chamada do solver termina cooperativamente
entre etapas, podendo ainda ocupar o executor durante algum tempo.

Antes da aplicação, uma secção protegida verifica novamente a revisão, o
identificador do conjunto de dados, a configuração em memória e os hashes dos
ficheiros de configuração e dados mestre. Uma mudança termina em `stale`. O
snapshot validado e o comprovativo `applied` são guardados numa única transação
SQLite. Só depois é publicado o estado preparado, sem suspender a secção final.
Falhas de persistência anteriores ao commit preservam o plano anterior. Um
comprovativo durável permite recuperar uma confirmação de commit perdida.

A migração acrescenta apenas a tabela `load_jobs` em `data/plans.db`. No arranque,
o mecanismo existente restaura o último snapshot válido; o gestor mantém os
comprovativos aplicados e marca tarefas incompletas como `failed`, código
`interrupted`. Estas exigem novo carregamento. Não se retomam candidatos parciais.
O armazenamento deve ser persistente e o servidor deve executar uma única
instância com um worker da API, como no serviço atual; vários processos exigiriam
coordenação adicional do plano ativo.

## Tempos e diagnóstico

Os registos `backend.loading` incluem `load_id`, fase, duração, decisão das
validações, motivos de aprovação e exceções técnicas. `timings_ms` distingue:

- `preparing`: preparação do ficheiro;
- `initial_construction`: construção do primeiro candidato;
- `construction`: todas as chamadas de construção, incluindo candidatos;
- `candidate_search`: procura de candidatos;
- `normalization`, `validation`: medições das respetivas etapas (desde
  07/10/2026 já não há fase `robustness`: a robustez é calculada em segundo
  plano depois da gravação e não entra na decisão);
- `optimization`: chamada completa do otimizador;
- `analytics`: preparação do estado, análises e serialização;
- `persistence`: transação final e publicação.

Os tempos são inclusivos e acumulados: normalização pode estar dentro de
construção, e construção dentro da procura. **Não somar as fases para obter o
tempo total.** O orçamento configurado do otimizador orienta a procura e as
decisões sobre iniciar trabalho; não é um timeout HTTP nem garante que toda a
construção, normalização e validação termine em 60 segundos.

## Validação desta alteração

Executar os testes de carregamento, persistência e API num diretório isolado com
cópias de `backend/`, `config/`, `scripts/`, `tests/` e `pyproject.toml`, pois alguns
testes existentes alteram configuração ou gravam snapshots relativos ao diretório
de execução:

```sh
python -m pytest -q tests/test_load_jobs.py tests/test_api_validation.py tests/test_plans.py tests/test_cpo.py
INCOMPOL_LONG_LOAD_TEST=1 python -m pytest -q tests/test_load_jobs.py -k http_remains_responsive
```

No diretório `frontend/`, executar `pnpm test` e `pnpm build`. O teste longo simula
151 segundos de cálculo e exige aceitação/consultas em menos de dois segundos,
mantendo o plano anterior consultável. Os outros testes cobrem aplicação única,
aprovação sem novo cálculo, bloqueio, cancelamento concorrente, revisão e
configuração alteradas, rollback, comprovativos após reinício, recuperação de
ligação, HTML do proxy e falha de atualização do ecrã.

Em 08/09/2026, o teste no navegador através de um túnel isolado usou um ISOP
sintético e o otimizador real. Duas consultas foram interrompidas, a página foi
atualizada e a mesma tarefa foi recuperada e aprovada, com um único pedido de
confirmação e nenhum erro JavaScript. Os dados de produção não foram substituídos.

O ensaio representativo reutilizou os dados do snapshot guardado de 01.09
(93 operações, 81 dias), com todas as máquinas inicialmente livres. Não corresponde
a uma reprodução do ficheiro exato das confirmações interrompidas.

| Medida | Diagnóstico anterior | Ensaio final com o gestor |
| --- | --- | --- |
| Tempo até ao candidato validado | 71,8 s | 81,0 s |
| Construção inicial | 31,0 s | 31,4 s |
| Procura de candidatos | 38,6 s | 47,2 s |
| Segmentos | 666 | 666 |
| Física, cobertura e janela JIT | Aprovadas | Aprovadas |
| Decisão | Aprovação necessária | Aprovação necessária |

No ensaio final, as quantidades por lote coincidiram com o snapshot. Os motivos
continuaram a ser risco de entrega, risco de envio para subcontratação e robustez
abaixo do limite (este último motivo deixou de existir em 07/10/2026: a
robustez passou a ser só informação). O maior atraso medido no ciclo de consultas assíncrono foi
266 ms e o plano anterior permaneceu disponível. Estes tempos não demonstram uma
aceleração do motor: a alteração permite acompanhar e concluir o trabalho sem
manter um pedido HTTP aberto durante todo o cálculo.

Após a atualização do serviço, as respostas de conjunto de dados, segmentos,
lotes, indicadores e validações coincidiram integralmente com as anteriores.
