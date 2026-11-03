#!/usr/bin/env bash
# 실험 38 1단계(시뮬 0): 10시즌 visit + 20개 재생을 병렬로 돌리고 analyze. 저장소 루트에서 실행한다.
#   bash experiments/38_ranker_miss/run_all.sh [병렬 수, 기본 3]
set -euo pipefail
P="${1:-3}"
cd "$(dirname "$0")/../.."
LOG=experiments/38_ranker_miss/run_log
mkdir -p "$LOG"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
jobs=()
for s in 33 34 35 36 37 38 39 40 41 42; do
  for k in 0 1; do
    [[ -f experiments/38_ranker_miss/replay/S${s}_s${k}.json ]] || jobs+=("replay --season $s --seed $k")
  done
  [[ -f experiments/38_ranker_miss/visit/S${s}.json ]] || jobs+=("visit --season $s")
done
printf '%s\n' "${jobs[@]}" | xargs -P "$P" -I{} sh -c \
  'python -I experiments/38_ranker_miss/an38.py {} >> experiments/38_ranker_miss/run_log/$(echo "{}" | tr " " "_" | tr -d "-").log 2>&1 && echo "done: {}" || echo "FAILED: {}"'
python -I experiments/38_ranker_miss/an38.py analyze
echo "ALL DONE"
