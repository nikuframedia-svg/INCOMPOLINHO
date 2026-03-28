# PP1 — Industrial APS Scheduler

Production planning scheduler for stamping factories.
Factory: Incompol (5 presses, 59 tools, ~94 SKUs, 14 clients).

## Requirements

- **Python >= 3.10** (uses `dataclass(slots=True)` and `X | Y` union syntax)
- Dependencies: `pip install -r requirements.txt`

## Run

```bash
python -m pytest tests/ -v
```

## Structure

- `backend/` — Scheduler, analytics, simulator, parser, transform
- `config/` — Factory master data (`incompol.yaml`) + scheduler config (`factory.yaml`)
- `frontend/` — React + TypeScript console UI
- `tests/` — 410+ tests
