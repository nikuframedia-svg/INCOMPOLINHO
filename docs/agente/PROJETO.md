# Projeto — receitas verificadas, ambientes e controlos

Skill: `fundador-nao-tecnico` v5.1.0 em `/home/luis/.claude/skills/fundador-nao-tecnico/SKILL.md`
(origem: `SKILL-3.md` entregue pelo fundador a 19/10/2026; versão 4.3.0 guardada em `~/.claude/skill-backups/`).

## Ambientes
| Ambiente | Onde | Notas |
| --- | --- | --- |
| Produção Incompol | árvore `/home/luis/projects/INCOMPOLINHO` (ramo `codex/prodplan-aps-trust-loop-v2`) | backend `incompolinho-backend.service` (uvicorn :8010), frontend `incompolinho-public-frontend.service` (vite preview de `frontend/dist`, :53868), túnel `incompolinho-public-tunnel.service` (cloudflared quick tunnel) |
| Trabalho | `git worktree add -b <ramo> /home/luis/projects/INCOMPOLINHO-wt-<nome> HEAD` | ligar `frontend/node_modules` e `tests/fixtures/private` por symlink |
| Dados vivos | `data/*.db` (plans, replan, audit, robustness), `config/factory.yaml` | nunca editar à mão nem fazer commit do factory.yaml |
| Dados privados de teste | `tests/fixtures/private/` (gitignored); cópias em `~/incompolinho-private/fixtures/` | manifestos commitados em `tests/fixtures/snapshots/`; congelar com `scripts/freeze_snapshot_fixture.py` |

Link público: `https://<nome>.trycloudflare.com` — **muda se o túnel ou o servidor reiniciar** (quick tunnel). Ver o atual: `journalctl --user -u incompolinho-public-tunnel.service | grep trycloudflare | tail -1`.

## Comandos verificados (19/10/2026)
- Backend, ficheiros alvo: `/home/luis/projects/INCOMPOLINHO/.venv/bin/python -m pytest -q <ficheiros>` (na raiz da worktree).
- Backend completo (~35 min, ~3700 testes): `PP1_REQUIRE_PRIVATE=1 … -m pytest tests/ -q -p no:cacheprovider`.
- Scripts fora do pytest exigem `PP1_DATA_DIR` e `PP1_CONFIG_PATH` em cópias temporárias (guarda `runtime_guard`).
- Lint: `/home/luis/projects/INCOMPOLINHO/.venv/bin/ruff check backend tests`.
- Frontend: `cd frontend && npx tsc -b && npx eslint src && npm test` (node tests + vitest).

## Publicar (regra AGENTS §7)
1. Testes alvo + suíte completa uma vez na versão a publicar.
2. Na árvore de produção: `git status` só pode mostrar `config/factory.yaml` e `docs/auditoria-browser-2026-10-02/live-before.json`; nenhum job pendente (`GET /api/data/replan-jobs?pending=true`).
3. Backup: `data/*.db` (sqlite backup) + `config/factory.yaml` para `~/incompolinho-private/backups/pre-<commit>-<data>/`.
4. `git merge --ff-only <ramo>`; se houver frontend: `scripts/deploy/build_frontend.sh`.
5. `systemctl --user restart incompolinho-backend.service incompolinho-public-frontend.service` (nunca o túnel).
6. Verificar serviços ativos, `curl` ao link público e log sem erros (`.run-logs/backend.log`).
Recuperação: código por `git` (commit anterior); dados pela pasta de backup.

## Controlos existentes
- `tests/test_refusal.py`: proíbe `HTTPException(4xx, str(exc))` nas APIs; `frontend/tests/refusal.test.tsx`: proíbe `alert(`.
- Gates físicos/coverage no backend (`backend/scheduler/gates.py`, `validation.py`), guarda de histórico no commit (`backend/plans/store.py`, `frozen.historical_schedule_changes`).
- Sem CI remoto: os controlos são locais (testes + lint) antes de publicar.

## Limitações conhecidas
- Golden master (`scripts/golden`) com referência desatualizada desde 14/10/2026.
- ISOPs muito grandes (≥130 operações) podem esgotar o tempo de replaneamento (80 s).
