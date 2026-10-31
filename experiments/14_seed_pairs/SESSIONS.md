# 실험 14 — 진행 방식과 파일 소유

관리자: 2026-10-31 세션(이 회차 전체). [작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다.

## 결정 — 클라우드 작업 세션을 따로 열지 않는다

약 6.4만 시뮬로 실험 12보다 작다. 실험 10~13의 평가 캐시가 남은 같은 컨테이너(4코어)에서 돌린다. 사전 계산 4개는 프로세스 4개로 동시에,
계정 검증은 실험 13에서 확인한 대로 프로세스 4개(시나리오 2개씩)로 돌린다(한 프로세스는 Python 한 코어에 묶인다).

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run14.py` · `analyze14.py` · `tests/test_exp14_*.py` · `run_log/` · `results.md` | 관리자 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## 인터페이스

- 사전 계산 `precompute_PB15s<k>.json`(k = 4~7): 실험 12와 같다. 합친 판 `precompute_U2a.json` · `U2b` · `U4n` · `merges.json`: 실험 13과 같다.
- 계정 실행 요약: 실험 10 [SESSIONS.md](../10_rankerless_start/SESSIONS.md#인터페이스--실행-요약-json)와 같다. 파일 `<sid>_P177_<기호>_<예산>.json`(기호 `U2a` · `U2b` · `U4n`).
