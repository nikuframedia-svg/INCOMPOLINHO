#!/usr/bin/env bash
# Portão de publicação do INCOMPOLINHO (plano Passo 1f).
#
# Uso: scripts/gate.sh [--fast] [--base <commit>] [--only ruff,pytest,golden,frontend]
#
#   --fast   golden master só com o subconjunto rápido
#            (F2 quick, F2 normal rev124, F3 avaria pequena, F4 movimento)
#   --base   commit para decidir se o frontend mudou
#            (por omissão: o commit da referência do golden master)
#   --only   corre só alguns passos (para depurar; o resultado é INCOMPLETO)
#
# Passos:
#   1. ruff 0.15.18 em backend/ tests/ scripts/
#   2. pytest completo com PP1_REQUIRE_PRIVATE=1 -rs: as fixtures privadas
#      entram por uma ligação simbólica temporária em tests/fixtures/private,
#      criada só se não existir e removida (e verificada) logo a seguir
#   3. golden master desta árvore contra a referência (scripts/golden)
#   4. frontend (lint, test, build) só se frontend/ mudou desde --base
#
# Sai com código diferente de zero se algum passo falhar (3 se incompleto).
# Nunca escreve na árvore viva nem nos dados reais: o golden master corre em
# cópias em ~/incompolinho-private/golden/runs/.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LIVE_TREE=${PP1_LIVE_TREE:-/home/luis/projects/INCOMPOLINHO}
PY=${PP1_PYTHON:-$LIVE_TREE/.venv/bin/python}
RUFF=${PP1_RUFF:-$LIVE_TREE/.venv/bin/ruff}
RUFF_VERSION=0.15.18
GOLDEN=${PP1_GOLDEN_DIR:-$HOME/incompolinho-private/golden}
PRIVATE_SRC=${PP1_PRIVATE_FIXTURES_SRC:-$LIVE_TREE/tests/fixtures/private}
FIXTURE_LINK=$ROOT/tests/fixtures/private

FAST=0
BASE=""
ONLY="ruff,pytest,golden,frontend"
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1 ;;
    --base) BASE=$2; shift ;;
    --only) ONLY=$2; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done

STAMP=$(date +%Y%m%d-%H%M%S)
HEAD_SHORT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo semgit)
LOG_DIR=$GOLDEN/gate-logs/$STAMP-$HEAD_SHORT
mkdir -p "$LOG_DIR" && chmod 700 "$GOLDEN/gate-logs" "$LOG_DIR"

NAMES=(); STATES=(); TIMES=(); NOTES=()
record() { NAMES+=("$1"); STATES+=("$2"); TIMES+=("$3"); NOTES+=("$4"); }
wants() { case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

LINK_CREATED=0
remove_link() {
  if [ "$LINK_CREATED" = 1 ]; then
    rm -f -- "$FIXTURE_LINK"
    LINK_CREATED=0
    if [ -e "$FIXTURE_LINK" ] || [ -L "$FIXTURE_LINK" ]; then
      echo "ERRO: a ligação temporária $FIXTURE_LINK não foi removida." >&2
      return 1
    fi
  fi
  return 0
}
trap 'remove_link' EXIT INT TERM

echo "Portão de publicação: $ROOT ($HEAD_SHORT), registos em $LOG_DIR"
if [ "$ROOT" = "$(cd "$LIVE_TREE" && pwd)" ]; then
  echo "AVISO: a correr na árvore de produção; o plano pede um worktree por passo."
fi

# 1. ruff --------------------------------------------------------------------
if wants ruff; then
  start=$SECONDS
  version=$("$RUFF" --version 2>/dev/null | awk '{print $2}')
  if [ "$version" != "$RUFF_VERSION" ]; then
    record "ruff" "FALHOU" $((SECONDS - start)) "versão $version (esperada $RUFF_VERSION)"
  elif (cd "$ROOT" && "$RUFF" check backend tests scripts) > "$LOG_DIR/ruff.log" 2>&1; then
    record "ruff $RUFF_VERSION" "OK" $((SECONDS - start)) "sem avisos"
  else
    record "ruff $RUFF_VERSION" "FALHOU" $((SECONDS - start)) \
      "$(grep -c '^[A-Z][0-9]' "$LOG_DIR/ruff.log" || true) avisos (ver ruff.log)"
  fi
fi

# 2. pytest ------------------------------------------------------------------
if wants pytest; then
  start=$SECONDS
  note=""
  ok=1
  if [ -e "$FIXTURE_LINK" ] || [ -L "$FIXTURE_LINK" ]; then
    note="fixtures privadas já presentes"
  elif [ -d "$PRIVATE_SRC" ]; then
    ln -s "$PRIVATE_SRC" "$FIXTURE_LINK" && LINK_CREATED=1
    note="ligação temporária às fixtures privadas"
  else
    ok=0
    note="fixtures privadas em falta ($PRIVATE_SRC)"
  fi
  if [ "$ok" = 1 ]; then
    (cd "$ROOT" && PP1_REQUIRE_PRIVATE=1 PYTHONDONTWRITEBYTECODE=1 \
      "$PY" -m pytest tests -q -rs -p no:cacheprovider) > "$LOG_DIR/pytest.log" 2>&1
    status=$?
    remove_link || { status=1; note="$note; LIGAÇÃO NÃO REMOVIDA"; }
    if [ "$LINK_CREATED" = 0 ] && [ "$note" = "ligação temporária às fixtures privadas" ]; then
      note="$note (removida)"
    fi
    result=$(grep -E '^(=+ )?[0-9]+ (passed|failed)|[0-9]+ (passed|failed|error)' \
      "$LOG_DIR/pytest.log" | tail -n 1 | sed 's/=//g; s/^ *//')
    if [ "$status" = 0 ]; then
      record "pytest completo" "OK" $((SECONDS - start)) "$result; $note"
    else
      record "pytest completo" "FALHOU" $((SECONDS - start)) "$result; $note (ver pytest.log)"
    fi
  else
    record "pytest completo" "FALHOU" $((SECONDS - start)) "$note"
  fi
fi

# 3. golden master -----------------------------------------------------------
if wants golden; then
  start=$SECONDS
  label="golden master"
  [ "$FAST" = 1 ] && label="golden master (rápido)"
  missing=""
  for item in baseline stability.json calibration.json pristine/MANIFEST.json; do
    [ -e "$GOLDEN/$item" ] || missing="$missing $item"
  done
  if [ -n "$missing" ]; then
    record "$label" "FALHOU" 0 "em falta em $GOLDEN:$missing"
  else
    suffix=""
    [ "$FAST" = 1 ] && suffix="-fast"
    OUT=$GOLDEN/captures/gate-$STAMP-$HEAD_SHORT$suffix
    flags=()
    [ "$FAST" = 1 ] && flags+=(--fast)
    "$PY" -B "$ROOT/scripts/golden/capture.py" --golden "$GOLDEN" --code "$ROOT" \
      --out "$OUT" "${flags[@]}" > "$LOG_DIR/golden-capture.log" 2>&1
    capture_status=$?
    "$PY" -B "$ROOT/scripts/golden/compare.py" "$GOLDEN/baseline" "$OUT" \
      --stability "$GOLDEN/stability.json" > "$LOG_DIR/golden-compare.log" 2>&1
    compare_status=$?
    counts=$(grep -cE '^  F[0-9]+_\S+ +IDÊNTICO' "$LOG_DIR/golden-compare.log" || true)
    equivalent=$(grep -cE '^  F[0-9]+_\S+ +EQUIVALENTE' "$LOG_DIR/golden-compare.log" || true)
    if [ "$capture_status" = 0 ] && [ "$compare_status" = 0 ]; then
      record "$label" "OK" $((SECONDS - start)) \
        "$counts idênticos, $equivalent equivalentes ($OUT)"
    else
      record "$label" "FALHOU" $((SECONDS - start)) \
        "captura=$capture_status comparação=$compare_status (ver golden-compare.log)"
    fi
  fi
fi

# 4. frontend ----------------------------------------------------------------
if wants frontend; then
  start=$SECONDS
  if [ -z "$BASE" ] && [ -e "$GOLDEN/baseline/SUMMARY.json" ]; then
    BASE=$("$PY" -c 'import json,sys; print((json.load(open(sys.argv[1])).get("code_identity") or {}).get("commit") or "")' \
      "$GOLDEN/baseline/SUMMARY.json")
  fi
  if [ -z "$BASE" ]; then
    record "frontend" "FALHOU" 0 "sem commit de base (use --base)"
  else
    changed=$( { git -C "$ROOT" diff --name-only "$BASE" -- frontend;
                 git -C "$ROOT" ls-files --others --exclude-standard -- frontend; } | sort -u)
    if [ -z "$changed" ]; then
      record "frontend" "SALTADO" 0 "sem alterações em frontend/ desde ${BASE:0:7}"
    else
      modules=$(readlink -f "$ROOT/frontend/node_modules" 2>/dev/null || true)
      live_frontend=$(cd "$LIVE_TREE" && pwd)/frontend
      if [ "$ROOT" != "$(cd "$LIVE_TREE" && pwd)" ] && [[ "$modules" == "$live_frontend"* ]]; then
        record "frontend" "FALHOU" 0 \
          "node_modules é uma ligação para a produção: o build (tsc -b) escreveria lá; instalar node_modules próprio no worktree"
      else
        if command -v pnpm > /dev/null 2>&1; then PM=(pnpm); else PM=(npm run); fi
        failed=""
        for script in lint test build; do
          if ! (cd "$ROOT/frontend" && "${PM[@]}" "$script") > "$LOG_DIR/frontend-$script.log" 2>&1; then
            failed="$failed $script"
          fi
        done
        if [ -z "$failed" ]; then
          record "frontend (${PM[*]})" "OK" $((SECONDS - start)) "lint, test e build"
        else
          record "frontend (${PM[*]})" "FALHOU" $((SECONDS - start)) "falhou:$failed"
        fi
      fi
    fi
  fi
fi

remove_link || record "fixtures privadas" "FALHOU" 0 "ligação temporária não removida"

# Resumo ---------------------------------------------------------------------
echo
echo "=== Portão de publicação: resumo ==="
final=0
for index in "${!NAMES[@]}"; do
  printf '  %-26s %-9s %6ss  %s\n' "${NAMES[$index]}" "${STATES[$index]}" \
    "${TIMES[$index]}" "${NOTES[$index]}"
  [ "${STATES[$index]}" = "FALHOU" ] && final=1
done
if [ "$ONLY" != "ruff,pytest,golden,frontend" ] && [ "$final" = 0 ]; then
  echo "Resultado: INCOMPLETO (só: $ONLY). Não serve para publicar."
  exit 3
fi
if [ "$final" = 0 ]; then
  echo "Resultado: VERDE. Pode seguir para a publicação (AGENTS §7)."
else
  echo "Resultado: VERMELHO. Não publicar; ver os registos em $LOG_DIR."
fi
exit $final
