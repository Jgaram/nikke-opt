# 실험 7 검증 조합 선정

[`select_val.py`](select_val.py)가 실험 6 [`select_comps.py`](../06_control_menu/select_comps.py)의 규칙을 그대로 쓰고 규모만 바꿔 골랐다: 최소 등장 1회(실험 6은 3회 — 16개 규모에서 3은 수리가 조합을 모두 빼고, 2는 레이어 대상 프리카가 빠진다. 검증 조합은 기법 성능을 재는 용도다), 할당 1-1-3 5, 1-2-2 4, 2-1-2 4, redhood 3(합 16, 범위 15~17), 시드 `20261030`, 실험 6 개발 조합 32개와 같은 구성 제외. 기법을 돌리기 전에 골라 고정했다.

- 후보 348개 중 개발 조합과 같은 구성 32개 제외 → 316개, 평가 오류 없음 316개, 상·중 구간 214개
- 평가 316회(기본 레이어 + `accumulate` 1회씩), 이번 실행의 새 시뮬 0회(나머지는 캐시 — 2026-10-29 첫 실행은 316회). 평가기 nikke-calc-rs 89d2e64
- 규칙 점검: 통과
- 수리: 없음

| id | 틀 | 배치 순서 | 기본 레이어 딜(억) | 태그 |
|---|---|---|---:|---|
| v01 | 1-1-3 | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 아니스 : 스타 · 미하라 : 본딩 체인 · 프리바티 | 44.8 | band:high ranker layer_target layer:미하라 : 본딩 체인 charge_light charge_n:1 gauge_mid |
| v02 | 1-1-3 | 아니스 : 스타 · 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 프리바티 | 44.3 | band:high ranker no_layer_target charge_mid charge_n:2 gauge_slow charger_candidate |
| v03 | 1-1-3 | 아니스 : 스타 · 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 앨리스 | 35.3 | band:high swap layer_target layer:앨리스 charge_heavy charge_n:3 gauge_slow charger_candidate |
| v04 | 1-1-3 | 리타 · 그레이브 · 신데렐라 : 크리스탈 웨이브 · 레이 · 모더니아 | 23.1 | band:mid ranker no_layer_target charge_none charge_n:0 gauge_fast |
| v05 | 1-1-3 | 리타 · 그레이브 · 앨리스 · 홍련 : 흑영 · 모더니아 | 20.4 | band:mid ranker layer_target layer:앨리스 layer:홍련 : 흑영 charge_mid charge_n:2 gauge_fast charger_candidate |
| v06 | 1-2-2 | 아니스 : 스타 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 브리드 : 사일런트 트랙 · 프리카 | 36.5 | band:high swap layer_target layer:프리카 charge_heavy charge_n:3 gauge_slow charger_candidate |
| v07 | 1-2-2 | 나유타 · 리버렐리오 · 플로라 · 디젤 : 윈터 스위츠 · 목단 | 30.7 | band:high ranker no_layer_target charge_mid charge_n:2 gauge_slow charger_candidate |
| v08 | 1-2-2 | 츠바이 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 브리드 : 사일런트 트랙 · 마스트 : 로망틱 메이드 | 26.6 | band:mid swap layer_target layer:츠바이 layer:마스트 : 로망틱 메이드 charge_light charge_n:1 gauge_fast charger_candidate |
| v09 | 1-2-2 | 토브 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 브리드 : 사일런트 트랙 · 마스트 : 로망틱 메이드 | 25.8 | band:mid swap layer_target layer:토브 layer:마스트 : 로망틱 메이드 charge_light charge_n:1 gauge_mid charger_candidate |
| v10 | 2-1-2 | 토브 · 아르카나 : 포츈 메이트 · 도로시 : 세렌디피티 · 드레이크 · 솔린 : 프로스트 티켓 | 36.5 | band:high ranker layer_target layer:토브 charge_none charge_n:0 gauge_fast |
| v11 | 2-1-2 | 토브 · 아르카나 : 포츈 메이트 · 드레이크 · 레이 · 솔린 : 프로스트 티켓 | 28.8 | band:high ranker layer_target layer:토브 charge_none charge_n:0 gauge_fast |
| v12 | 2-1-2 | 토브 · 아르카나 : 포츈 메이트 · 도로시 : 세렌디피티 · 에이다 · 솔린 : 프로스트 티켓 | 25.5 | band:mid swap layer_target layer:토브 layer:에이다 charge_light charge_n:1 gauge_mid charger_candidate |
| v13 | 2-1-2 | 미란다 · 그레이브 · 에이다 · 미하라 : 본딩 체인 · D : 킬러 와이프 | 23.2 | band:mid swap layer_target layer:미란다 layer:에이다 layer:미하라 : 본딩 체인 miranda_rule charge_mid charge_n:2 gauge_fast charger_candidate |
| v14 | redhood | 아니스 : 스타 · 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 디젤 : 윈터 스위츠 · 레드 후드 | 32.9 | band:high swap no_layer_target charge_heavy charge_n:3 gauge_slow charger_candidate |
| v15 | redhood | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 아니스 : 스타 · 미하라 : 본딩 체인 · 레드 후드 | 30.9 | band:high swap layer_target layer:미하라 : 본딩 체인 charge_mid charge_n:2 gauge_slow charger_candidate |
| v16 | redhood | 리타 · 그레이브 · 레드 후드 · 레이 · 모더니아 | 17.1 | band:mid swap no_layer_target charge_light charge_n:1 gauge_fast charger_candidate |

니케별 등장 조합 수: 라피 : 레드 후드 8 · 브리드 : 사일런트 트랙 8 · 디젤 : 윈터 스위츠 7 · 아니스 : 스타 6 · 그레이브 4 · 토브 4 · 레드 후드 3 · 레이 3 · 리타 3 · 모더니아 3 · 미하라 : 본딩 체인 3 · 솔린 : 프로스트 티켓 3 · 아르카나 : 포츈 메이트 3 · 도로시 : 세렌디피티 2 · 드레이크 2 · 마스트 : 로망틱 메이드 2 · 앨리스 2 · 에이다 2 · 프리바티 2 · D : 킬러 와이프 1 · 나유타 1 · 리버렐리오 1 · 목단 1 · 미란다 1 · 신데렐라 : 크리스탈 웨이브 1 · 츠바이 1 · 프리카 1 · 플로라 1 · 홍련 : 흑영 1
