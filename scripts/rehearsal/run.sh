#!/usr/bin/env bash
# Ensaio de publicação numa cópia isolada (tempos reais, orçamentos reais).
#
# Uso: run.sh <pristine> <code> <tag> <actions> <core> <outdir> [opções do rehearse.py]
#   <pristine>  pasta com data/ e config/ (ex.: ~/incompolinho-private/golden/pristine)
#   <code>      árvore de código a ensaiar (worktree ou git archive)
#   <actions>   ex.: recalc | recalc,outage31 | move (ver rehearse.py)
#   <core>      núcleo para taskset (um núcleo por ensaio)
# Cria <outdir>/rt_<tag>/ com uma cópia nova dos dados; nunca toca na árvore viva.
set -euo pipefail
if [ $# -lt 6 ]; then
  sed -n '2,9p' "$0"
  exit 2
fi
PRISTINE=$(realpath "$1"); CODE=$(realpath "$2"); TAG=$3; ACTIONS=$4; CORE=$5; OUT=$(realpath -m "$6")
shift 6
PY=${PP1_PYTHON:-/home/luis/projects/INCOMPOLINHO/.venv/bin/python}
HERE=$(cd "$(dirname "$0")" && pwd)
RT=$OUT/rt_$TAG
mkdir -p "$OUT"
rm -rf "$RT"
mkdir -p "$RT"
cp -a "$PRISTINE/data" "$RT/data"
cp -a "$PRISTINE/config" "$RT/config"
cd "$RT"
set +e
env -u PYTHONPATH PP1_DATA_DIR="$RT/data" PP1_CONFIG_PATH="$RT/config/factory.yaml" \
  PP1_AUTO_ROBUSTNESS=0 PP1_LLM_BACKEND=none PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 \
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  taskset -c "$CORE" "$PY" -B "$HERE/rehearse.py" --code "$CODE" --oracle-dir "$CODE/tests" \
  --out "$OUT/$TAG.json" --actions "$ACTIONS" "$@" > "$OUT/$TAG.log" 2>&1
STATUS=$?
set -e
echo "EXIT=$STATUS" >> "$OUT/$TAG.log"
exit $STATUS
