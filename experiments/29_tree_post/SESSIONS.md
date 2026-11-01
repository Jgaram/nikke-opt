# 실험 29 — 진행 방식과 파일 소유

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 2026-11-01 사용자 답: 실험 세션 2 + 화면 세션 1을 동시에, 모두 Opus.
관리자: 2026-11-01 세션 `session_01MQimn1hHyNLGJ9YAEh3RW5`. 공용 코드 · 사전 등록 · 이 파일을 커밋한 뒤 작업 세션 3개를 연다.

## 분담

| 작업 세션 | 맡은 일 |
|---|---|
| E1 | 실험 29 실행: w1 · w2 · w3 · w4 |
| E2 | 실험 29 실행: w5 · w6 · w7 · w8 |
| V | 현황판(`web/`)에 편성안 계층 화면 만들기(아래 §화면) |

세션(2026-11-01 14:06 UTC 시작, 모두 Opus): E1 `session_01MQimn1sJUd2GhN666PeMHF` · E2 `session_01MQimn2N1P6GM6fcpwz1AZJ` · V `session_01MQimn24kJvEo8JduWRcDGy`.

- 결과는 결정론이라 어느 컨테이너에서 돌려도 같다. 시뮬 횟수는 세션별로 기록한다(캐시가 컨테이너마다 따로).
- 작업 세션은 다른 세션을 열지 않는다. 공용 코드(`run29.py` · `tree28.py` 등)를 고쳐야 하면 직접 고치지 않고 관리자에게 알린다.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `experiments/29_tree_post/` 의 `README.md` · `SESSIONS.md` · `run29.py` · `results.md` · `analysis.json`, `tests/test_exp29.py`, `experiments/28_plan_tree/` 전부 | 관리자 |
| `experiments/29_tree_post/run_log/w<k>.json` · `w<k>.jsonl.gz` · `run_log/run_E<n>.jsonl` · `run_log/ops/**`(자기 계정 것) | 그 계정을 맡은 E 세션 |
| `web/**`(`app.js` · `build.py` · `style.css` · `index.html` · `README.md` · `icons/` · `sync_icons.py`), `tests/test_web.py`, `.github/workflows/pages.yml` | V |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

`run_log/ops/` 파일 이름은 계정이 들어간 구성 id의 해시라 E1 · E2가 겹치지 않는다.

## E 세션 절차 (`LIST` = 맡은 계정 넷, `N` = 1 또는 2, 저장소 루트에서)

```bash
# 0. 평가기 — add_repo(Jgaram/nikke-calc-rs)로 붙여 /home/user/nikke-calc-rs에 clone한 뒤
git -C /home/user/nikke-calc-rs rev-parse --short HEAD     # 89d2e64여야 한다(다르면 fetch --depth 1 origin 89d2e64 && checkout -q 89d2e64)
bash tools/setup_evaluators.sh
mkdir -p .cache/exp29
# 1. 계정 넷을 동시에(백그라운드 한 명령, 제한 2시간)
R=experiments/29_tree_post/run29.py
for s in $(echo $LIST | tr , ' '); do
  (source .cache/evaluators.env && python $R run --only $s --tag E$N > .cache/exp29/$s.log 2>&1) &
done; wait
# 2. 확인: run_log/w<k>.json 넷, 각 "evaluator" "nikke-calc-rs 89d2e64", "errors" 0
# 3. 커밋(맡은 파일만: run_log/w<k>.* · run_log/run_E<N>.jsonl · run_log/ops/) → git fetch origin main && git merge origin/main
#    → python -m unittest discover -s tests -t . → git push origin HEAD:main
```

- 계정 하나가 끝날 때마다 그 계정 파일을 커밋 · push해도 된다(세션이 끊겨도 남는다).
- 2시간 제한에 끊기면 같은 명령을 다시 돌린다(끝난 계정은 건너뛰고, 운용 탐색은 run_log/ops 캐시로 빨리 따라잡는다). 다시 돌린 사실을 보고에 적는다.
- **보고(E → 관리자, `send_message`):** 커밋 해시 · 테스트 결과(통과 · 실패 · 생략 수) · 계정별 `C_final.ratio` · `search_sims` · `C_final.sims` · `subs_post.sims` · `seconds` · 막힌 점.
  막히면(평가기 빌드 · 접근 · 시간) 우회하거나 가짜 결과로 채우지 않고 바로 알린다.

## 화면 (V)

지금 현황판은 실험 22(랭커 대조)만 보여 준다. 여기에 **가상 계정 w1~w8의 편성안 계층**을 보는 화면을 더한다. 시뮬은 하지 않는다.

**데이터:** `experiments/29_tree_post/analysis.json`이 있으면 그것, 없으면 `experiments/28_plan_tree/analysis.json`(지금 있음). 어느 쪽인지 화면에 적는다.
둘 다 `rows[]`의 모양이 같다.

```
rows[] = {
  scenario: "w1", name: "계정 조건 설명", best: 최선 합(억),
  rep_J: {"A-B": J, "A-C": J, "B-C": J},
  classes[] = {                       // A · B · C 순
    name: "A" | "B" | "C", found: bool, note: "설명", total: 합(억), ratio: 최선 대비,
    decks: [[덱 값(억), [니케 5명(배치 순서)]] × 5],
    subs_count: 세부 분류 수(≥ 97%, 400에서 자름), subs_1deck: 그중 덱 하나만 바뀐 수,
    subs[] = {                        // 앞 3개 = 보일 것(바뀐 덱이 서로 겹치지 않음), 나머지 = 더보기(합 순, 20개까지)
      total: 합(억), J: 대표와 J, J_other: {"B": J, "C": J}(다른 대표와),
      changed: [바뀐 대표 덱 번호(1부터)], new_decks: [[니케 5명] …], new_values: [새 덱 값(억) …],
      out: [빠진 니케], in: [들어온 니케], moves: 옮기거나 바꿀 니케 수, new_unposted: 후처리 안 된 새 덱 수
    }
  }
}
실험 29에만 더 있는 것: C_final{ratio, J_A, J_B, sims …}, C_pre_post, subs_post{converged, sims}, 계정별 시뮬 수 — 없으면 무시
```

- 실험 28 파일에서 C는 「후처리 전」이다(note에 적혀 있다). `found: false`인 큰 분류는 「없음」으로 둔다.
- `new_unposted > 0`인 세부 분류는 「후처리 전 값」 표시를 붙인다.

**보여 줄 것:**
- 계정 고르기(w1~w8, 조건 설명 `name`).
- 큰 분류 A · B · C를 접었다 펴는 칸으로 둔다. 머리에는 최선 대비 %, 합, 다른 대표와의 J, 바꿀 니케 수(`rep_J`), note를 둔다. 펴면 대표 5덱을 기존 5×5 격자로 보여 주고 덱마다 값을 붙인다.
- 그 안에 세부 분류 앞 3개를 둔다. 각 칸에는 바뀐 덱 번호, 빠짐 → 들어옴 얼굴(같은 니케끼리 덱 사이 옮김이면 그렇게), 최선 대비 %, 대표와 J, 다른 대표와 J를 둔다.
  고르면(펴면) 그 5덱 격자를 보여 주고, 바뀐 덱을 강조한다.
- 「더보기」로 나머지(20개까지)를 펼친다. 개수는 `subs_count`이고, 20개 밖은 「외 n개」로 적는다.
- 기존 규칙을 따른다: 니케는 글자 없이 그림(얼굴 · 속성 · 버스트), 화면 낭독기용 `alt`에만 이름. 주력 딜러 표시는 쓰지 않는다. 새로 나온 니케 그림은 `web/sync_icons.py`로 받는다(nikke-analysis는 공개 레포).
- 맨 위 한 줄 설명: 큰 분류 = 대표끼리 J ≤ 0.2, 세부 분류 = 대표에서 덱 1~2개만 바꾼 것(J ≥ 0.5, 최선의 97% 이상). [실험 28](../28_plan_tree/README.md) 링크.
- 실험 22 화면은 그대로 둔다. 화면 간 이동(탭 등) 방식은 V가 정한다.
- `web/README.md` · `tests/test_web.py`를 함께 고친다. `python web/build.py --out _site`로 만들어 Playwright로 넓은 화면 · 좁은 화면(390px)을 찍어 확인한다.
- **보고(V → 관리자, `send_message`):** 커밋 해시 · 테스트 결과 · 화면 설명 · 스크린샷 경로(커밋하지 않음) · 남은 문제.
