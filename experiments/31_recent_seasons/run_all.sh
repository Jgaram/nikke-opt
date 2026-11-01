#!/usr/bin/env bash
# 실험 31 전체 실행(평가기가 있는 컨테이너 하나): B 시드 20개 → 시즌마다 코어 30 · members → 랭커 덱 → 분석(시뮬 0).
#
#   bash experiments/31_recent_seasons/run_all.sh          # 로그: .cache/exp31/, 진행: .cache/exp31/progress.log
#   JOBS=4 SEASONS="33 34" bash experiments/31_recent_seasons/run_all.sh
#
# - 작업 줄을 4개씩 동시에 돌린다(JOBS). 코어 30 · members(P)는 그 시즌 B 두 시드 뒤에 오도록,
#   두 묶음(시즌 넷) 뒤에 끼워 넣는다 — 기다리는 작업 없이 코어를 계속 쓴다.
# - 끝난 부분(part_*.json)은 run31.py가 건너뛴다. 끊기면 같은 명령을 다시 돌린다.
set -uo pipefail
cd "$(dirname "$0")/../.."
export R=experiments/31_recent_seasons/run31.py
export L=.cache/exp31
export LOGD=experiments/31_recent_seasons/run_log
mkdir -p "$L"
JOBS=${JOBS:-4}
read -r -a SS <<< "${SEASONS:-33 34 35 36 37 38 39 40 41 42}"

job() {   # $1 시즌, $2 부분(쉼표로 여럿)
  source .cache/evaluators.env
  if python "$R" run --season "$1" --part "$2" > "$L/S$1_${2//,/_}.log" 2>&1; then
    echo "$(date -u +%H:%M:%S) done S$1 $2"
  else
    touch "$L/S$1.fail"; echo "$(date -u +%H:%M:%S) FAIL S$1 $2"
  fi
}
post() {  # $1 시즌: B 두 시드를 기다린 뒤 코어 30 · members
  until [[ -f $LOGD/S$1/part_B_s0.json && -f $LOGD/S$1/part_B_s1.json ]]; do
    [[ -f $L/S$1.fail ]] && { echo "$(date -u +%H:%M:%S) SKIP S$1 core30,members (B 실패)"; return; }
    sleep 20
  done
  job "$1" core30,members
}
export -f job post

lines=()
pend=()
for i in "${!SS[@]}"; do
  s=${SS[$i]}
  lines+=("B $s B_s0" "B $s B_s1")
  pend+=("$s")
  if (( i % 2 == 1 )) && (( ${#pend[@]} > 2 )); then   # 두 시즌 앞선 것부터 P를 끼운다
    lines+=("P ${pend[0]}" "P ${pend[1]}")
    pend=("${pend[@]:2}")
  fi
done
for s in "${pend[@]}"; do lines+=("P $s"); done

echo "$(date -u +%H:%M:%S) start: ${#lines[@]}개 작업, 동시 $JOBS" | tee -a "$L/progress.log"
printf '%s\n' "${lines[@]}" | xargs -P "$JOBS" -L 1 bash -c 'if [[ $0 == B ]]; then job "$1" "$2"; else post "$1"; fi' | tee -a "$L/progress.log"
( source .cache/evaluators.env && python "$R" rankers > "$L/rankers.log" 2>&1 ) \
  && echo "$(date -u +%H:%M:%S) done rankers" | tee -a "$L/progress.log" || echo "$(date -u +%H:%M:%S) FAIL rankers" | tee -a "$L/progress.log"
python "$R" analyze > "$L/analyze.log" 2>&1 \
  && echo "$(date -u +%H:%M:%S) done analyze" | tee -a "$L/progress.log" || echo "$(date -u +%H:%M:%S) FAIL analyze" | tee -a "$L/progress.log"
echo "$(date -u +%H:%M:%S) ALL END" | tee -a "$L/progress.log"
