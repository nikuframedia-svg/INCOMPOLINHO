#!/usr/bin/env bash
# Compila a versão final do frontend para frontend/dist, de forma atómica.
#
#   scripts/deploy/build_frontend.sh
#
# 1. Recusa compilar se frontend/ tiver alterações por guardar (só se publica
#    código que está num commit, AGENTS.md §7).
# 2. tsc -b (verificação de tipos) e vite build para frontend/dist.new.
# 3. Confirma que o resultado é a versão final (sem o cliente de
#    desenvolvimento do Vite e com ficheiros com hash no nome).
# 4. Troca dist.new -> dist (duas mudanças de nome, ~1 ms) e apaga a antiga.
# 5. Regista data, commit e ficheiro de entrada em .run-logs/frontend-build.log.
#
# O serviço público (vite preview) lê frontend/dist do disco a cada pedido:
# correr este script na árvore de produção publica a nova versão no próximo
# carregamento da página. Não reinicia nenhum serviço; ver deploy/README.md.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_DIR="$REPO_DIR/frontend"
DIST="$FRONTEND_DIR/dist"
STAGE="$FRONTEND_DIR/dist.new"
OLD="$FRONTEND_DIR/dist.old"
LOG_DIR="$REPO_DIR/.run-logs"
LOG_FILE="$LOG_DIR/frontend-build.log"

die() {
  echo "build_frontend: $*" >&2
  exit 1
}

cleanup() {
  # Se a troca ficou a meio, repõe a versão anterior; nunca deixa dist vazio.
  if [ ! -e "$DIST" ] && [ -d "$OLD" ]; then
    mv "$OLD" "$DIST"
  fi
  rm -rf "$STAGE"
}

[ -x "$FRONTEND_DIR/node_modules/.bin/vite" ] || die "falta $FRONTEND_DIR/node_modules (instalar dependências primeiro)"
[ -x "$FRONTEND_DIR/node_modules/.bin/tsc" ] || die "falta o TypeScript em $FRONTEND_DIR/node_modules"

mkdir -p "$LOG_DIR"
exec 9>"$LOG_DIR/frontend-build.lock"
flock -n 9 || die "já está outra compilação a decorrer"

# Restos de uma execução interrompida deste script (nunca são de outra origem).
rm -rf "$STAGE" "$OLD"

dirty="$(git -C "$REPO_DIR" status --porcelain --untracked-files=all -- frontend)"
if [ -n "$dirty" ]; then
  echo "$dirty" >&2
  die "frontend/ tem alterações por guardar; só se publica código num commit"
fi
commit="$(git -C "$REPO_DIR" rev-parse HEAD)"
branch="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

trap cleanup EXIT
cd "$FRONTEND_DIR"
export NODE_ENV=production
node_modules/.bin/tsc -b
node_modules/.bin/vite build --outDir dist.new --emptyOutDir

[ -f "$STAGE/index.html" ] || die "a compilação não produziu index.html"
if grep -q '/@vite/client' "$STAGE/index.html"; then
  die "index.html traz o cliente de desenvolvimento do Vite"
fi
entry="$(grep -oE '/assets/index-[A-Za-z0-9_-]+\.js' "$STAGE/index.html" | head -n 1 || true)"
[ -n "$entry" ] || die "index.html sem script de entrada com hash em /assets/"
[ -f "$STAGE$entry" ] || die "falta o ficheiro de entrada $entry"

if [ -e "$DIST" ]; then
  mv "$DIST" "$OLD"
fi
mv "$STAGE" "$DIST"
rm -rf "$OLD"
trap - EXIT

line="$(date '+%Y-%m-%dT%H:%M:%S%z') commit=$commit branch=$branch entry=$entry node=$(node --version)"
echo "$line" >>"$LOG_FILE"
echo "build_frontend: publicado em $DIST"
echo "build_frontend: $line"
