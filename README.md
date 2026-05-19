# PP1 — Industrial APS Scheduler

Production planning scheduler for stamping factories.
Factory: Incompol (5 presses, 59 tools, ~94 SKUs, 14 clients).

## Run with Docker (recommended)

No Python or Node needed — just Docker. Works on Linux x86-64 and Mac alike:

```bash
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

## Structure

- `backend/` — Scheduler, analytics, simulator, parser, transform, copilot API
- `frontend/` — React 19 + TypeScript + Vite console UI
- `config/` — Factory master data (`incompol.yaml`) + scheduler config (`factory.yaml`)
- `docker/` — Nginx + Supervisor configs; `Dockerfile` + `docker-compose.yml` at root
- `tests/` — 420+ tests
