# 실험 13 — 진행 방식과 파일 소유

관리자: 2026-10-31 세션(이 회차 전체). [작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다.

## 결정 — 클라우드 작업 세션을 따로 열지 않는다

새 사전 계산이 없고 계정 검증 약 2.2만 시뮬이라 한 컨테이너(4코어)로 충분하다. 실험 10~12의 평가 캐시가 남은 같은 컨테이너에서 돌린다.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run13.py` · `analyze13.py` · `tests/test_exp13_*.py` · `run_log/` · `results.md` | 관리자 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

## 인터페이스

- 계정 실행 요약: 실험 10 [SESSIONS.md](../10_rankerless_start/SESSIONS.md#인터페이스--실행-요약-json)와 같다. 파일 `<sid>_P177_<기호>_<예산>.json`(기호 `U4` · `U2w`).
- 합친 판 `precompute_U4.json` · `precompute_U2w.json`: 실험 11 형식의 `sets` · `set_totals` · `coef` · `final`에 `kind` · `seeds` · `part`(각 시드 기록의 앞 1/part) ·
  `comps`(합친 구성 수) · `core` · `ge195` · `squad_seeds`(최선 5덱 덱별로 그 구성이 든 시드들) · `single`(시드별 사전 계산 최종) · `pick`(고르기 판 기호) · `stages`를 둔다.
  `sims` · `seconds`는 출처 시드들의 값을 쓴 평가 수 비례로 더한 것이다(새 시뮬 아님).
- `merges.json`: 관찰용 합친 판 목록(U2 · U3 · E2 · E3, 8벌 · 계수 없음).
