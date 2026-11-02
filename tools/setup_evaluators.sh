#!/usr/bin/env bash
# 클라우드 세션에서 평가기를 준비한다. 결과는 .cache/evaluators.env에 쓴다(커밋 안 함).
#
#   bash tools/setup_evaluators.sh            # Rust nikke-sim만
#   bash tools/setup_evaluators.sh --python   # + Python 원본(nikke-calc, Rust 포팅 기준 커밋)
#   source .cache/evaluators.env && python -m nikke_opt.eval "크라운"
#
# 셸 상태는 명령 사이에 이어지지 않으므로 평가기를 쓰는 명령마다 `source .cache/evaluators.env &&`를 붙인다.
# nikke-calc-rs는 비공개 레포라 세션에 붙어 있어야 한다(세션 소스·환경 Repositories·add_repo 중 하나).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RS_DIR="${NIKKE_CALC_RS_DIR:-/home/user/nikke-calc-rs}"
CALC_DIR="${NIKKE_CALC_DIR:-/home/user/jgaram/nikke-calc}"
CALC_COMMIT=67835ca3033a95482749ea2db35a8ee2a0856a92  # nikke-calc-rs의 포팅 기준 원본(2026-11-02, 원본 master: 1·2버 자동 버스트 순환 + 신규 니케 3명 · 렐릭 베젤 큐브)
ENV_FILE="$ROOT/.cache/evaluators.env"
WITH_PYTHON=0
[[ "${1:-}" == "--python" ]] && WITH_PYTHON=1

mkdir -p "$ROOT/.cache"
: > "$ENV_FILE"

if [[ ! -d "$RS_DIR/.git" ]]; then
  echo "nikke-calc-rs가 없다: $RS_DIR — 이 세션에 Jgaram/nikke-calc-rs를 붙이고 다시 실행한다" >&2
  exit 1
fi
(cd "$RS_DIR" && cargo build --release -q -p nikke-cli)  # rust-toolchain.toml이 고른 툴체인을 rustup이 받는다
SIM_BIN="$RS_DIR/target/release/nikke-sim"
echo "export NIKKE_SIM_BIN=$SIM_BIN" >> "$ENV_FILE"
echo "nikke-sim: $SIM_BIN (nikke-calc-rs $(git -C "$RS_DIR" rev-parse --short HEAD))"

if (( WITH_PYTHON )); then
  if [[ ! -d "$CALC_DIR/.git" ]]; then
    GIT_LFS_SKIP_SMUDGE=1 git clone -q --depth 1 https://github.com/Jgaram/nikke-calc "$CALC_DIR"
  fi
  if [[ "$(git -C "$CALC_DIR" rev-parse HEAD)" != "$CALC_COMMIT" ]]; then
    git -C "$CALC_DIR" fetch -q --depth 1 origin "$CALC_COMMIT"
    git -C "$CALC_DIR" checkout -q "$CALC_COMMIT"
  fi
  echo "export NIKKE_CALC_DIR=$CALC_DIR" >> "$ENV_FILE"
  echo "nikke-calc: $CALC_DIR ($(git -C "$CALC_DIR" rev-parse --short HEAD))"
fi

echo "→ $ENV_FILE"
