# 실험 11 — 진행 방식과 파일 소유

관리자: 2026-10-30 세션(이 회차 전체). [작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다.

## 결정 — 클라우드 작업 세션을 따로 열지 않는다

실험 10과 같은 이유다(약 8~9만 시뮬, 한 컨테이너 4코어). 실험 10의 평가 캐시가 남은 같은 컨테이너에서 돌려
P177 사전 계산 · K177 · P177 계정 실행의 앞부분을 캐시로 다시 쓴다. 분석 스크립트는 같은 컨테이너의 서브에이전트가 결과를 보기 전에 만든다.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run11.py` · `tests/test_exp11_run.py` · `run_log/` | 관리자 |
| `analyze11.py` · `tests/test_exp11_analyze.py` · `results.md`(생성물) | 분석 담당(서브에이전트) — 관리자가 통합 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## 인터페이스

- 계정 실행 요약: 실험 10 [SESSIONS.md](../10_rankerless_start/SESSIONS.md#인터페이스--실행-요약-json)와 같다. 파일 `<sid>_P177_<기법>_<예산>.json`,
  기법 = `PB15` · `PB30` · `PN` · `PM` · `P`(실험 10 P177 사전 계산) · `K`(K177).
- 사전 계산 `precompute_<기호>.json`: 실험 10 형식(`pool` · `budget` · `evals` · `sims` · `seconds` · `sets` · `set_totals` · `coef` · `final` · `history` · `kicks`)에
  `name`, `stages`(단계마다 `what` · `budget` · `evals` · `sims` · `seconds` · `best` · `history` · `kicks`)를 더하고, PN · PM은 `narrowed`(좁힌 60명), PN은 `coef_inner`(2단계 계수)도 둔다.
  `budget` · `evals` · `sims` · `seconds`는 단계 합이다(PN · PM은 재사용한 1단계 포함).
