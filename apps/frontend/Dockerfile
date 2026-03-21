# ── Stage 1: Build ──────────────────────────────────────────────
# Build context is the monorepo root (.)
FROM node:22-alpine AS builder

WORKDIR /app

# Copy workspace config
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY apps/frontend/package.json apps/frontend/

# Install pnpm and dependencies
RUN corepack enable && corepack prepare pnpm@10.30.3 --activate
RUN pnpm install --frozen-lockfile

# Copy frontend source and build
COPY apps/frontend/ apps/frontend/

# Vite embeds env vars at build time
ARG VITE_APP_MODE=mock
ARG VITE_API_BASE_URL=/api
ENV VITE_APP_MODE=$VITE_APP_MODE
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN pnpm --filter pp1-frontend build

# ── Stage 2: Serve with Nginx ──────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY apps/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder
COPY --from=builder /app/apps/frontend/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
