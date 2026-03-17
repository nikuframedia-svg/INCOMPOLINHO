# Backend PP1

FastAPI + SQLAlchemy 2.0 + Alembic + PostgreSQL.
O backend NÃO faz scheduling client-side. Guarda snapshots, planos e audit.
Pydantic V2. Python 3.9 compat (all files have `from __future__ import annotations`).
Nunca editar migrations existentes.

## Domains
- nikufra — ISOP ingest + data management
- snapshot — Immutable snapshots
- plan — Plan persistence
- audit — Audit trail
- run_events — Append-only event log
- solver — CP-SAT (OR-Tools), recovery, Monte Carlo
- copilot — GPT-4o assistant (10 tools, function calling)
- stock_alerts — Alert persistence + coverage engine
- firewall — Decision integrity
- dqa — Data quality / TrustIndex
- learning — Learning engine
- ledger — Decision ledger
- settings — Engine settings (41 params, JSON persistence)
- pipeline — Unified scheduling pipeline (ISOP→schedule)

## Copilot
- `POST /v1/copilot/chat` — GPT-4o with 10 function-calling tools
- `GET /v1/copilot/tools` — List available tools
- Requires `PP1_OPENAI_API_KEY` env var
