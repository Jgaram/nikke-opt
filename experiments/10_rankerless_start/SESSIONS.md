# 실험 10 — 진행 방식과 파일 소유

관리자: 2026-10-30 새 세션(이 회차 전체). [작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다.

## 결정 — 클라우드 작업 세션을 따로 열지 않는다

- 계산량이 약 15~16만 시뮬(한 컨테이너 4코어, 약 25회/초로 2시간 안팎)이라 세션을 나눠 얻는 시간보다
  세션마다 평가기 빌드 · 캐시 분리 · 병합의 비용과 위험이 크다고 본다. 한 컨테이너에서 실행해 시뮬 수를 한곳에서 센다.
- README 「진행 방식」의 (2) `analyze10.py` · 테스트는 같은 컨테이너의 서브에이전트가 (1)과 동시에 만든다(결과를 보기 전).
- 검증 실행은 백그라운드로 돌리고 실행 단위로 결과 파일을 남겨 끊기면 이어 돌린다.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run10.py` · `roster_ssr.json` · `tests/test_exp10_run.py` · `run_log/` | 관리자 |
| `analyze10.py` · `tests/test_exp10_analyze.py` · `results.md`(생성물) | 분석 담당(서브에이전트) — 관리자가 통합 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## 인터페이스 — 실행 요약 JSON

`run10.py search`는 실행마다 `<dir>/<sid>_P<pool>_<기법>_<예산>.json`(요약)과 `.jsonl.gz`(평가 기록)를 쓴다.
기법 이름은 `K` · `K+E` · `R` · `R+E` · `G` · `G+E` · `P` · `P+E`, pool은 `60` 또는 `177`.

```json
{
  "scenario": "v1", "name": "미보유 무작위 3명 C", "pool": 60, "method": "R+E", "budget": 2000,
  "evals": 1834, "errors": 0,
  "start": {"evals": 136, "pack": 160.2},
  "history": [{"evals": 136, "pack": 160.2, "kick": false}, {"evals": 236, "pack": 171.0, "kick": false}],
  "pre_order": {"evals": 1750, "pack": 184.1},
  "kicks": [{"evals": 836, "best": 183.0, "improved": true}],
  "final": {"total": 185.5, "squads": [[43.2, ["a", "b", "c", "d", "e"]]]},
  "alt": {"total": 183.9, "squads": [[43.2, ["..."]]], "shared_nikkes": 23},
  "alt20": {"total": 179.0, "squads": [], "shared_nikkes": 20},
  "sims_during": 812, "seconds": 140.2
}
```

- 값은 억(1e8) 단위, 기본 레이어(후처리 전) 180초 총딜. `pack` = 그 시점까지 평가한 모든 구성의 정확한 최선 5덱 합.
- `start` = 출발 단계 직후(K 옮기기 · R 설계 · G 구성 · P 옮기기). `history`의 첫 줄 = `start`, 이후 라운드마다 한 줄,
  마지막 줄 = 배치 순서 다듬기 뒤(`final.total`과 같다). `kick: true`는 그 라운드 직전에 킥을 했다는 뜻이다.
- `pre_order` = 배치 순서 다듬기 직전. `kicks[].best` = 킥 시점의 전체 최선, `improved` = 다음 킥(또는 다듬기 전)까지 전체 최선이 올랐는가.
- `alt` = 최선 5덱과 덱(구성)을 2개 이하만 공유하는 최선 5덱(실험 9 정의), `alt20` = 그중 니케 공유 20명 이하. 없으면 `total` 0 · `squads` [].
- K(P60)는 실험 9 L0k 검증 기록(`../09_account_pack/run_log/`)을 `run10.py import-k`로 이 형식으로 옮긴다(`kicks` [], `alt20`은 기록에서 다시 조립).
- 공유 사전 계산은 `<dir>/precompute_P<pool>.json`: `{"pool", "budget", "evals", "sims", "seconds", "sets": [[[5명] × 5] × ≤8],
  "set_totals": [...], "coef": {니케: 계수}, "final": {...}}`.
