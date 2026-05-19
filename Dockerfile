# syntax=docker/dockerfile:1
#
# PP1 — Industrial APS Scheduler
# Multi-stage image: builds the React frontend, then bundles it with the
# Python backend behind Nginx, supervised by Supervisor.
#
# Architecture-agnostic: every base image and dependency below has both
# linux/amd64 and linux/arm64 builds, so `docker compose up --build`
# produces a native image on a Linux x86-64 PC and on an Apple-Silicon Mac
# alike. See DOCKER.md for cross-architecture publishing.

# ── Stage 1: Build frontend (React 19 + Vite, pnpm) ───────────
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend

# The frontend uses pnpm (pnpm-lock.yaml, lockfileVersion 9.0).
# corepack ships with Node 22 — pin pnpm for reproducible builds.
RUN corepack enable && corepack prepare pnpm@9.15.4 --activate

# Install dependencies strictly from the lockfile.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build the static bundle (tsc -b && vite build).
COPY frontend/ .
RUN pnpm run build

# ── Stage 2: Python + Nginx runtime ───────────────────────────
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Nginx (reverse proxy + static) + Supervisor (process manager).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

# Python dependencies (ortools, scikit-learn, fastapi, ...).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend code + factory config + helper scripts.
COPY backend/ backend/
COPY config/ config/
COPY scripts/ scripts/

# Frontend static bundle from the build stage.
COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html

# Nginx + Supervisor configs.
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Runtime directories: SQLite DBs (audit, learning) and ISOP drop folder.
# Mounted as volumes by docker-compose so data survives container rebuilds.
RUN mkdir -p /app/data /app/isop

EXPOSE 80

# Health: hits Nginx, which proxies to the backend — covers the whole stack.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost/api/copilot/health',timeout=4).status==200 else 1)"

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
