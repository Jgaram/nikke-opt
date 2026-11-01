# 실험 22 — 진행 방식과 파일 소유

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 2026-11-01 사용자 답: 작업 세션 4개(Sonnet)로 병렬.
관리자: 2026-11-01 세션 `session_01MQimn5CDbvH37JKpu9CsSc`. 공용 코드 · 사전 등록을 커밋한 뒤 작업 세션 4개를 연다.

## 결정 — 관리자 1 + 작업 세션 4(시즌 둘씩)

- 사전 계산 16개(시즌 8 × 보스 2)는 서로 독립이고 각각 약 1.2만 시뮬이다. 한 컨테이너(4코어)에 프로세스 4개를 동시에 두면 약 1시간이다(실험 15와 같은 방식).
- 결과(최선 5덱)는 결정론이라 어느 컨테이너에서 돌려도 같다. 시뮬 횟수는 세션별로 기록한다(캐시가 컨테이너마다 따로).
- 작업 세션은 다른 세션을 열지 않는다.

| 작업 세션 | 시즌 | 풀 |
|---|---|---|
| W1 | 4 · 23 | 73 · 124 |
| W2 | 9 · 28 | 86 · 139 |
| W3 | 14 · 34 | 99 · 155 |
| W4 | 18 · 40 | 109 · 170 |

**분담 변경(2026-11-01 05:15 UTC):** W3 `session_01MQimn23vCToexEWX28MoLA` · W4 `session_01MQimn54eCUNqkQ2ag5jrVp`는 평가기 저장소 붙이기(`add_repo`)가
자동 권한 검사에 막혀 시작하지 못했다. 두 세션은 취소했다. S14 · S34는 관리자 컨테이너에서(`meta_M.json`), S18은 W1, S40은 W2가 자기 몫 4개를 끝낸 뒤 이어서 돌린다.
W1 `session_01MQimn5oGWQFXjkqejUa5A1` · W2 `session_01MQimn2DzC41Dus13p26ry7`(05:11 UTC 시작).

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `seasons22.py` · `seasons.json` · `run22.py` · `analyze22.py` · `results.md` · `run_log/rankers_*.json` · `tests/test_exp22.py` | 관리자 |
| `run_log/precompute_S<k>_<보스>.json` · `.jsonl.gz`, `run_log/meta_W<n>.json` | 그 시즌을 맡은 세션(위 분담 변경 반영) |
| `run_log/meta_M.json` · `run_log/members_*.json` | 관리자 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

작업 세션이 공용 코드를 고쳐야 하면(버그 등) 직접 고치지 않고 관리자에게 알린다.

## 작업 세션 절차 (`A`, `B` = 맡은 시즌, 저장소 루트에서)

```bash
# 0. 평가기 — add_repo(Jgaram/nikke-calc-rs)로 붙여 /home/user/nikke-calc-rs에 clone한 뒤
git -C /home/user/nikke-calc-rs rev-parse --short HEAD     # 89d2e64여야 한다(다르면 checkout -q 89d2e64 — 얕은 clone이면 fetch --depth 1 origin 89d2e64)
bash tools/setup_evaluators.sh
mkdir -p .cache/exp22
# 1. 사전 계산 4개를 동시에(백그라운드 한 명령, 제한 2시간)
R=experiments/22_ranker_check/run22.py
for s in A B; do for b in nocore core30; do
  (source .cache/evaluators.env && python $R precompute --season $s --boss $b > .cache/exp22/S$s-$b.log 2>&1) &
done; done; wait
# 2. 확인: run_log/precompute_S<k>_<보스>.json 4개, 각 "evals" 15000 근처 · "evaluator" "nikke-calc-rs 89d2e64"
# 3. meta_W<n>.json: 세션 · 시즌 · 실행별 sims · seconds(각 json의 값) · 합계 · 시작/끝 시각(UTC) · 막힌 점
# 4. 커밋(맡은 파일만) → git fetch origin main && git merge origin/main → python -m unittest discover -s tests -t . → git push origin HEAD:main
```

- 2시간 제한에 끊기면 같은 명령을 다시 돌린다(끝난 실행은 건너뛰고, 끊긴 실행은 캐시 덕에 빨리 따라잡는다). 다시 돌린 사실을 meta에 적는다.
- **보고(작업 세션 → 관리자, `send_message`):** 커밋 해시 · 테스트 결과(통과 · 실패 · 생략 수) · 실행별 sims · seconds · 최선 5덱 합 · 막힌 점.
  막히면(평가기 빌드 · 접근 · 시간) 우회하거나 가짜 결과로 채우지 않고 바로 알린다.
