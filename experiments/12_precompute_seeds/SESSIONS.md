# 실험 12 — 진행 방식과 파일 소유

관리자: 2026-10-30 세션(이 회차 전체). [작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다.

## 결정 — 클라우드 작업 세션을 따로 열지 않는다

실험 10 · 11과 같은 이유다(약 10만 시뮬, 한 컨테이너 4코어). 실험 10 · 11의 평가 캐시가 남은 같은 컨테이너에서 돌려
PBD · PBS의 s0 출발과 K · PB15(s0) 기록을 다시 쓴다. 사전 계산 5개는 프로세스 5개로 동시에 돌린다(평가 캐시 sqlite 공유).

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run12.py` · `analyze12.py` · `tests/test_exp12_*.py` · `run_log/` · `results.md` | 관리자 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## 인터페이스

- 계정 실행 요약: 실험 10 [SESSIONS.md](../10_rankerless_start/SESSIONS.md#인터페이스--실행-요약-json)와 같다. 파일 `<sid>_P177_<기호>_<예산>.json`.
- 사전 계산 `precompute_<기호>.json`: 실험 11 형식에 `seed` · `kind` · `t195`(195억 첫 도달 평가 수, 없으면 null) · `core`(뼈대 4명이 한 덱) · `restarts`(PBS 등반자)를 더한다.
  10k 판은 `cut_from`(원본 기호)을 두고 `sims` · `seconds`는 원본에서 평가 수 비례로 적는다.
