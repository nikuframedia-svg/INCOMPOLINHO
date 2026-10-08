# PP1 — Industrial APS Scheduler

Production planning scheduler for stamping factories.
Factory: Incompol (5 presses, 59 tools, ~94 SKUs, 14 clients).

## Technical And Functional Manual

Portuguese technical and functional manual: [editable source](docs/manual-tecnico-funcional-incompol.md). Covers business rules, KPI formulas, screens, workflows, architecture, and implementation limitations. Rendered documents and screenshots containing operational data are kept locally.

## Local data

This repository contains the application source, tests, and documentation. ISOP spreadsheets, databases, backups, private regression snapshots, exported plans, audit logs, and screenshots containing operational data stay outside Git. Tests that require private snapshots skip when those files are absent.

## Run with Docker (recommended)

No Python or Node needed — just Docker. Works on Linux x86-64 and Mac alike:

```bash
cp .env.example .env              # one-time: create the env file
docker compose up --build -d      # → http://localhost:3000
```

See **[DOCKER.md](DOCKER.md)** for the full guide (env, ISOP loading,
multi-architecture publishing, troubleshooting).

## Run from source

Requirements:

- **Python >= 3.10** (uses `dataclass(slots=True)` and `X | Y` union syntax)
- Backend: `pip install -r requirements.txt`
- Frontend: `pnpm install` then `pnpm run build` (in `frontend/`)

Tests:

```bash
python -m pytest tests/ -v
```

## Operator Workflow

- ISOP loading runs in the background and resumes tracking after a page refresh.
  See the [loading API and recovery contract](docs/isop-loading.md).
- Use **Configuração -> Administração / Avançado -> Ver dados ISOP** for a
  read-only audit of imported references and historical configured SKUs.
- Use **Correções de planeamento** and **Subcontratações** for persistent
  exceptions. The default supplier lead is 5 working days (shown as 7 calendar
  days); subcontract material is released 5 working days before planned
  supplier dispatch, while normal material remains anchored to customer delivery.
- Use **Gantt** for the graphical plan and **Tabela** for searchable/sortable
  daily navigation; shifts are read from `config/factory.yaml`.
- Capacity week buckets expose `workday_count` and use the legend documented in
  the [operator guide](docs/operator-guide.md).

## Structure

- `backend/` — Scheduler, analytics, simulator, parser, transform, copilot API
- `frontend/` — React 19 + TypeScript + Vite console UI
- `config/` — Factory master data (`incompol.yaml`) + scheduler config (`factory.yaml`)
- `docker/` — Nginx + Supervisor configs; `Dockerfile` + `docker-compose.yml` at root
- `tests/` — 528 tests
