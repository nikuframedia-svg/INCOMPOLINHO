#!/usr/bin/env bash
# Reconstrói a imagem PP1 (amd64 + arm64) e envia para o Docker Hub.
# O Luís depois faz:  docker compose pull && docker compose up -d
set -euo pipefail
cd "$(dirname "$0")"

docker buildx build \
  --builder pp1-builder \
  --platform linux/amd64,linux/arm64 \
  -t yrdftugyihjonkpmnohugiyftd7r6s/pp1-scheduler:latest \
  --push .

echo
echo "==> FEITO. Imagem nova no Docker Hub: yrdftugyihjonkpmnohugiyftd7r6s/pp1-scheduler:latest"
