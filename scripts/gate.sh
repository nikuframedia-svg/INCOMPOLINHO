#!/usr/bin/env bash
# Portão de publicação do INCOMPOLINHO (plano Passo 1f).
#
# Uso: scripts/gate.sh [--fast] [--rehearsal] [--allow-harness-change]
#                      [--base <commit>] [--only ruff,pytest,golden,frontend,rehearsal]
#
#   --fast       golden master só com o subconjunto rápido (F2 quick, F2 normal
#                rev124, F3 avaria pequena, F4 e F4b movimentos): resultado
#                INCOMPLETO (saída 3), não serve para publicar
#   --rehearsal  acrescenta o ensaio real (tempos reais) da referência e desta
#                árvore: recalcular, avaria PRM031, avaria pequena, movimento;
#                tempos até +10 % e recalcular abaixo de 60 s. Obrigatório nos
#                passos que mexem no motor (plano, regra 2)
#   --allow-harness-change
#                o harness desta árvore (scripts/golden/{flows,capture,compare}.py,
#                scripts/gate.sh) pode diferir do da referência: corre o desta
#                árvore e a diferença passa a aviso. Sem esta opção é FALHA, e
#                o golden master corre com a cópia do harness guardada com a
#                referência (<golden>/baseline/harness/)
#   --base       commit para decidir se o frontend mudou
#                (por omissão: o commit da referência do golden master)
#   --only       corre só alguns passos (para depurar; o resultado é INCOMPLETO)
#
# Passos:
#   1. ruff 0.15.18 em backend/ tests/ scripts/
#   2. pytest completo com PP1_REQUIRE_PRIVATE=1 -rs: as fixtures privadas
#      entram por uma ligação simbólica temporária em tests/fixtures/private,
#      criada só se não existir e removida (e verificada) logo a seguir
#   3. golden master desta árvore contra a referência (scripts/golden)
#   4. frontend (lint, test, build) só se frontend/ mudou desde --base
#   5. ensaio real (só com --rehearsal ou --only ...,rehearsal)
#
# Saída: 0 VERDE; 1 VERMELHO (algum passo falhou); 3 INCOMPLETO (--fast,
# --only ou golden parcial); 130/143 INTERROMPIDO (Ctrl-C/SIGTERM: o passo em
# curso é parado com todos os seus processos e a ligação temporária removida).
# Nunca escreve na árvore viva nem nos dados reais: o golden master e o ensaio
# correm em cópias em ~/incompolinho-private/golden/.
set -uo pipefail
# Sem controlo de tarefas: cada passo fica no grupo da sua sessão (setsid).
set +m

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LIVE_TREE=${PP1_LIVE_TREE:-/home/luis/projects/INCOMPOLINHO}
PY=${PP1_PYTHON:-$LIVE_TREE/.venv/bin/python}
RUFF=${PP1_RUFF:-$LIVE_TREE/.venv/bin/ruff}
RUFF_VERSION=0.15.18
GOLDEN=${PP1_GOLDEN_DIR:-$HOME/incompolinho-private/golden}
PRIVATE_SRC=${PP1_PRIVATE_FIXTURES_SRC:-$LIVE_TREE/tests/fixtures/private}
FIXTURE_LINK=$ROOT/tests/fixtures/private
ALL_STEPS="ruff,pytest,golden,frontend"

FAST=0
REHEARSAL=0
ALLOW_HARNESS=0
BASE=""
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) FAST=1 ;;
    --rehearsal) REHEARSAL=1 ;;
    --allow-harness-change) ALLOW_HARNESS=1 ;;
    --base) BASE=$2; shift ;;
    --only) ONLY=$2; shift ;;
    -h|--help) sed -n '2,37p' "$0"; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done
STEPS=${ONLY:-$ALL_STEPS}
if [ -z "$ONLY" ] && [ "$REHEARSAL" = 1 ]; then STEPS="$STEPS,rehearsal"; fi

STAMP=$(date +%Y%m%d-%H%M%S)
HEAD_SHORT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo semgit)
LOG_DIR=$GOLDEN/gate-logs/$STAMP-$HEAD_SHORT
mkdir -p "$LOG_DIR" && chmod 700 "$GOLDEN/gate-logs" "$LOG_DIR"

NAMES=(); STATES=(); TIMES=(); NOTES=()
record() { NAMES+=("$1"); STATES+=("$2"); TIMES+=("$3"); NOTES+=("$4"); }
wants() { case ",$STEPS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

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

# Cada passo corre na sua própria sessão (setsid) e em segundo plano, para o
# `wait` ser interrompível: um sinal pára o grupo inteiro do passo (pytest,
# capture.py e os processos de cada fluxo) e o portão sai com erro.
CHILD_PGID=""
RUN_GROUP=""
run_step() {
  local log=$1
  shift
  setsid "$@" > "$log" 2>&1 < /dev/null &
  CHILD_PGID=$!
  wait "$CHILD_PGID"
  local status=$?
  CHILD_PGID=""
  return $status
}

on_signal() {
  local name=$1 code=$2
  trap '' INT TERM
  echo >&2
  echo "INTERROMPIDO ($name): a parar o passo em curso..." >&2
  if [ -n "$CHILD_PGID" ]; then
    kill -TERM -- "-$CHILD_PGID" 2>/dev/null
    for _ in $(seq 1 20); do
      kill -0 -- "-$CHILD_PGID" 2>/dev/null || break
      sleep 0.5
    done
    kill -KILL -- "-$CHILD_PGID" 2>/dev/null
  fi
  remove_link || true
  if [ -n "$RUN_GROUP" ]; then rm -rf -- "${GOLDEN:?}/runs/$RUN_GROUP"; fi
  echo "Resultado: INTERROMPIDO ($name). Não publicar; registos em $LOG_DIR." >&2
  exit "$code"
}
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'remove_link' EXIT

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
  elif run_step "$LOG_DIR/ruff.log" env -C "$ROOT" "$RUFF" check backend tests scripts; then
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
    run_step "$LOG_DIR/pytest.log" env -C "$ROOT" PP1_REQUIRE_PRIVATE=1 PYTHONDONTWRITEBYTECODE=1 \
      "$PY" -m pytest tests -q -rs -p no:cacheprovider
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
  for item in baseline/SUMMARY.json stability.json calibration.json pristine/MANIFEST.json \
      baseline/harness/flows.py baseline/harness/capture.py baseline/harness/compare.py \
      baseline/harness/gate.sh; do
    [ -e "$GOLDEN/$item" ] || missing="$missing $item"
  done
  if [ -n "$missing" ]; then
    record "$label" "FALHOU" 0 "em falta em $GOLDEN:$missing"
  else
    PINNED=$(readlink -f "$GOLDEN/baseline")/harness
    changed=""
    for name in flows.py capture.py compare.py; do
      cmp -s "$ROOT/scripts/golden/$name" "$PINNED/$name" || changed="$changed $name"
    done
    cmp -s "$ROOT/scripts/gate.sh" "$PINNED/gate.sh" || changed="$changed gate.sh"
    if [ -n "$changed" ] && [ "$ALLOW_HARNESS" = 0 ]; then
      record "$label" "FALHOU" 0 \
        "harness diferente do da referência:$changed (recapturar a referência; --allow-harness-change para uma mudança deliberada)"
    else
      HARNESS=$PINNED
      compare_flags=()
      harness_note="harness da referência"
      if [ -n "$changed" ]; then
        HARNESS=$ROOT/scripts/golden
        compare_flags+=(--allow-harness-change)
        harness_note="HARNESS ALTERADO (permitido):$changed"
      fi
      suffix=""
      capture_flags=()
      if [ "$FAST" = 1 ]; then
        suffix="-fast"
        capture_flags+=(--fast)
        compare_flags+=(--allow-subset)
      fi
      OUT=$GOLDEN/captures/gate-$STAMP-$HEAD_SHORT$suffix
      RUN_GROUP=$(basename "$OUT")
      run_step "$LOG_DIR/golden-capture.log" "$PY" -B "$HARNESS/capture.py" --golden "$GOLDEN" \
        --code "$ROOT" --out "$OUT" "${capture_flags[@]}"
      capture_status=$?
      RUN_GROUP=""
      run_step "$LOG_DIR/golden-compare.log" "$PY" -B "$PINNED/compare.py" "$GOLDEN/baseline" \
        "$OUT" --stability "$GOLDEN/stability.json" "${compare_flags[@]}"
      compare_status=$?
      counts=$(grep -cE '^  F[0-9]+[a-z]?_\S+ +IDÊNTICO' "$LOG_DIR/golden-compare.log" || true)
      equivalent=$(grep -cE '^  F[0-9]+[a-z]?_\S+ +EQUIVALENTE' "$LOG_DIR/golden-compare.log" || true)
      absent=$(grep -cE '^  F[0-9]+[a-z]?_\S+ +NÃO CAPTURADO' "$LOG_DIR/golden-compare.log" || true)
      if [ "$capture_status" = 0 ] && [ "$compare_status" = 0 ]; then
        record "$label" "OK" $((SECONDS - start)) \
          "$counts idênticos, $equivalent equivalentes; $harness_note ($OUT)"
      elif [ "$capture_status" = 0 ] && [ "$compare_status" = 3 ]; then
        record "$label" "PARCIAL" $((SECONDS - start)) \
          "$counts idênticos, $equivalent equivalentes, $absent não capturados; $harness_note"
      else
        record "$label" "FALHOU" $((SECONDS - start)) \
          "captura=$capture_status comparação=$compare_status (ver golden-compare.log)"
      fi
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
          if ! run_step "$LOG_DIR/frontend-$script.log" env -C "$ROOT/frontend" "${PM[@]}" "$script"; then
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

# 5. ensaio real ---------------------------------------------------------------
if wants rehearsal; then
  start=$SECONDS
  reference=""
  if [ -e "$GOLDEN/baseline/SUMMARY.json" ]; then
    reference=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("code") or "")' \
      "$GOLDEN/baseline/SUMMARY.json")
  fi
  if [ -z "$reference" ] || [ ! -e "$reference/backend/__init__.py" ]; then
    record "ensaio real" "FALHOU" 0 "código da referência em falta (${reference:-?})"
  else
    run_step "$LOG_DIR/rehearsal.log" "$PY" -B "$ROOT/scripts/rehearsal/gate_rehearsal.py" \
      --reference "$reference" --candidate "$ROOT" --pristine "$GOLDEN/pristine" \
      --out "$LOG_DIR/rehearsal"
    status=$?
    verdict=$(grep -E '^ensaio:' "$LOG_DIR/rehearsal.log" | tail -n 1)
    if [ "$status" = 0 ]; then
      record "ensaio real" "OK" $((SECONDS - start)) "${verdict:-sem resumo} (ver rehearsal.log)"
    else
      record "ensaio real" "FALHOU" $((SECONDS - start)) "${verdict:-saída $status} (ver rehearsal.log)"
    fi
  fi
fi

remove_link || record "fixtures privadas" "FALHOU" 0 "ligação temporária não removida"

# Resumo ---------------------------------------------------------------------
echo
echo "=== Portão de publicação: resumo ==="
final=0
partial=0
for index in "${!NAMES[@]}"; do
  printf '  %-26s %-9s %6ss  %s\n' "${NAMES[$index]}" "${STATES[$index]}" \
    "${TIMES[$index]}" "${NOTES[$index]}"
  [ "${STATES[$index]}" = "FALHOU" ] && final=1
  [ "${STATES[$index]}" = "PARCIAL" ] && partial=1
done
if ! wants rehearsal; then
  echo "  (ensaio real não corrido: --rehearsal, obrigatório nos passos que mexem no motor)"
fi
if [ "$final" = 1 ]; then
  echo "Resultado: VERMELHO. Não publicar; ver os registos em $LOG_DIR."
  exit 1
fi
why=""
[ -n "$ONLY" ] && why="$why só: $ONLY;"
[ "$FAST" = 1 ] && why="$why golden master rápido;"
[ "$partial" = 1 ] && [ "$FAST" = 0 ] && why="$why golden master parcial;"
if [ -n "$why" ]; then
  echo "Resultado: INCOMPLETO ($why) Não serve para publicar."
  exit 3
fi
echo "Resultado: VERDE. Pode seguir para a publicação (AGENTS §7)."
exit 0
