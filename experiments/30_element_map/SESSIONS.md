# 실험 30 — 진행 방식과 파일 소유

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 2026-11-01 사용자 답: 세션 여러 개, 약 20만 시뮬.
관리자: 2026-11-01 세션 `session_01MQimn3qXdHnM4DGPUwvYQL`. 공용 코드 · 사전 등록 · 이 파일을 커밋한 뒤 작업 세션 5개를 연다.

## 분담 — 속성마다 작업 세션 하나

| 작업 세션 | 속성(`enemy.code`) |
|---|---|
| E1 | 전격 |
| E2 | 풍압 |
| E3 | 철갑 |
| E4 | 수냉 |
| E5 | 작열 |

관리자는 `corecheck`(실험 22 S40 · S34 코어 30 재평가)와 분석 · 판단을 맡는다.

세션(2026-11-01 15:11 UTC 시작, 모두 Opus, 계획 `2707d17`): E1 `session_01MQimn21KSR17RzbGCYKY2n` · E2 `session_01MQimn4QKqYrcLv7LKBPp4c` ·
E3 `session_01MQimn5mAjyW7axDP2YbPQ6` · E4 `session_01MQimn3Z7u6zarS94mb3bBr` · E5 `session_01MQimn3Xd7YQ5EB2CF2eNwC`.

- B와 W는 같은 세션(같은 평가 캐시)에서 센다. W는 B 기록 앞부분을 쓰므로 B 다음에 돈다.
- 결과는 결정론이라 어느 컨테이너에서 돌려도 같다. 시뮬 횟수는 부분별 기록(`part_*.json`의 `sims`)으로 남는다.
- 작업 세션은 다른 세션을 열지 않는다. 공용 코드(`run30.py` · `tree28.py` 등)를 고쳐야 하면 직접 고치지 않고 관리자에게 알린다.
- 실험 29(다른 관리자)의 파일은 건드리지 않는다.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `experiments/30_element_map/` 의 `README.md` · `SESSIONS.md` · `run30.py` · `pre30.py` · `pre_map.*` · `results.md` · `analysis.json` · `run_log/corecheck_*.json`, `tests/test_exp30.py` | 관리자 |
| `experiments/30_element_map/run_log/<속성>/**`(`B_s0.jsonl.gz` · `B_s1.jsonl.gz` · `W.jsonl.gz` · `core30.jsonl.gz` · `part_*.json` · `maps.json`) | 그 속성을 맡은 E 세션 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## E 세션 절차 (`EL` = 맡은 속성, 저장소 루트에서)

```bash
# 0. 평가기 — add_repo(Jgaram/nikke-calc-rs)로 붙여 /home/user/nikke-calc-rs에 clone한 뒤
git -C /home/user/nikke-calc-rs rev-parse --short HEAD     # 89d2e64여야 한다(다르면 fetch --depth 1 origin 89d2e64 && checkout -q 89d2e64)
bash tools/setup_evaluators.sh
mkdir -p .cache/exp30
R=experiments/30_element_map/run30.py
# 1. B 시드 둘을 동시에(백그라운드 한 명령, 제한 2시간)
for p in B_s0 B_s1; do
  (source .cache/evaluators.env && python $R run --element $EL --part $p > .cache/exp30/$p.log 2>&1) &
done; wait
# 2. W(B 둘 다 끝난 뒤, 백그라운드 한 명령)
source .cache/evaluators.env && python $R run --element $EL --part W > .cache/exp30/W.log 2>&1
# 3. 코어 30 재평가(W 뒤). 지도 계산(maps.json)이 먼저 돈다
source .cache/evaluators.env && python $R run --element $EL --part core30 > .cache/exp30/core30.log 2>&1
# 4. 확인: run_log/$EL/part_{B_s0,B_s1,W,core30}.json 넷, 각 "evaluator" "nikke-calc-rs 89d2e64", "errors" 0(B · W)
# 5. 커밋(맡은 폴더 run_log/$EL/ 만) → git fetch origin main && git merge origin/main
#    → python -m unittest discover -s tests -t . → git push origin HEAD:main
```

- 부분 하나가 끝날 때마다 그 파일을 커밋 · push해도 된다(세션이 끊겨도 남는다).
- 2시간 제한에 끊기면 같은 명령을 다시 돌린다. 끝난 부분은 건너뛴다. 끊긴 부분은 처음부터 다시 돌지만 같은 요청은 평가 캐시에서 나온다.
  다시 돌린 사실을 보고에 적는다(그 부분의 `sims`는 다시 돈 실행의 값이라 끊긴 실행의 시뮬이 빠진다 — 끊긴 실행의 로그 마지막 시뮬 수를 함께 적는다).
- **보고(E → 관리자, `send_message`):** 커밋 해시 · 테스트 결과(통과 · 실패 · 생략 수) · 부분별 `sims` · `seconds` · B 시드별 `best` ·
  W `blocks` 수와 마지막 블록 · core30 `requests` · 막힌 점. 막히면(평가기 빌드 · 접근 · 시간) 우회하거나 가짜 결과로 채우지 않고 바로 알린다.
