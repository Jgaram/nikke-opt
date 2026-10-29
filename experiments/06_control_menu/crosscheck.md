# 실험 6 W1 — Rust ↔ Python 원본 대조

`crosscheck.py`가 만든다. 차이 = (Rust − Python) / Python, 총딜 기준. |차이| ≥ 1%(임시)는 **표시**.

## 조건

- 적: 평가기 기본(허수아비, 방어력 31784) · `sim`: 어댑터 기본(`expected: true` · `burst_gauge_mode: accumulate`) · `operation.control_mode`: 평가기 기본 `solo` · 육성: 기본 스펙
- Rust: null
- Python: null
- 실제 시뮬 횟수: Rust — · Python — (캐시 적중 Rust — · Python —)
- 실행 시각: — · 걸린 시간: Rust —초 · Python —초

## 조합

| 키 | 배치 순서 |
|---|---|
| A | 미란다 · 타키나 · 아인 · 루주 · 에이다 |
| B | 리타 · 민트 · 레이븐 · 프리카 · 레드 후드 |
| C | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 아니스 : 스타 · 미하라 : 본딩 체인 · 프리바티 |
| D | 리타 · 그레이브 · 레이 · 앨리스 · 모더니아 |

## 요청별 차이

| id | 조합 | 축 | 바꾼 것 | Rust 총딜 | Python 총딜 | 차이 | 차이가 가장 큰 니케 | 표시 |
|---|---|---|---|---:|---:|---:|---|---|
| A0 | A | base | 기본 레이어 · accumulate | 미실행 | 미실행 | — | — | |
| B0 | B | base | 기본 레이어 · accumulate | 미실행 | 미실행 | — | — | |
| C0 | C | base | 기본 레이어 · accumulate | 미실행 | 미실행 | — | — | |
| D0 | D | base | 기본 레이어 · accumulate | 미실행 | 미실행 | — | — | |
| A1 | A | gauge | 기본 레이어 · fixed | 미실행 | 미실행 | — | — | |
| C1 | C | gauge | 기본 레이어 · fixed | 미실행 | 미실행 | — | — | |
| A2 | A | auto | operation.auto: true | 미실행 | 미실행 | — | — | |
| B2 | B | auto | operation.auto: true | 미실행 | 미실행 | — | — | |
| A3 | A | solo | control_mode: warn (solo 조율 끔) | 미실행 | 미실행 | — | — | |
| B4 | B | click | 레드 후드 상시 톡톡이 3.6 | 미실행 | 미실행 | — | — | |
| B5 | B | click | 프리카 본인 풀버스트 홀드 | 미실행 | 미실행 | — | — | |
| D6 | D | reload | 모더니아 장전컨 A(before_fb_end 0.3) | 미실행 | 미실행 | — | — | |
| C6 | C | reload | 라피 : 레드 후드 장전컨 C(if_dry) | 미실행 | 미실행 | — | — | |
| C7 | C | cover | 미하라 : 본딩 체인 버스트 엄폐컨 | 미실행 | 미실행 | — | — | |
| D8 | D | cancel | 모더니아 · 레이 탄충 취소 | 미실행 | 미실행 | — | — | |
| B9 | B | burst_delay | 레드 후드 버스트 딜레이 2.0초 | 미실행 | 미실행 | — | — | |
| A9 | A | burst_pattern | 미란다 패턴 끔(전담 해제) | 미실행 | 미실행 | — | — | |
| A10 | A | burst_wait | 루주 wait_own_cooldown 3.0 | 미실행 | 미실행 | — | — | |
| A11 | A | tactic | 버충 택틱(담당 루주) | 미실행 | 미실행 | — | — | |
| D12 | D | camera | 카메라 앨리스(기본: 3번 레이) | 미실행 | 미실행 | — | — | |

## 표시 — 1% 이상 차이 나는 축

미실행.

## 판단

**미실행 (2026-10-29).** W1 세션에서 `Jgaram/nikke-calc-rs`를 붙이지 못했다 — `add_repo`가 세션 권한 검사에서 거부됐고, 지시대로 우회하지 않았다. Rust 빌드 전이라 대조를 돌리지 못했다. 요청 20개와 실행·표 코드는 준비되어 있어, 평가기가 있는 세션에서 `bash tools/setup_evaluators.sh --python` 뒤 `source .cache/evaluators.env && python experiments/06_control_menu/crosscheck.py --raw <scratchpad>/crosscheck_raw.jsonl`을 돌리면 이 파일이 결과로 바뀐다(판단 절은 그 뒤 손으로 쓴다).

요청 고르기: 조합 4개는 nikke-calc `baseline/`의 하네스 스쿼드(아인루주 · 레이븐레드후드 · 브리드라피 · 앨리스모더니아)에서 레이어 대상(미란다 · 에이다 · 아인 · 프리카 · 미하라 · 앨리스)과 차지형 비중이 다르게 섞이도록 골랐다. 각 축은 그 축이 실제로 작동하는 니케에 걸었다(예: 카메라는 기본 유도가 MG 레이라 게이지에 무영향인 D에서 앨리스로 옮김, 엄폐컨·탄충 취소는 MG, 버충은 base 충전이 느릴 수 있는 A의 SR 루주). 기준 요청(A0~D0)과 축 요청의 차이를 비교하면 큰 차이가 축 때문인지 조합 바탕 때문인지 가를 수 있다.
