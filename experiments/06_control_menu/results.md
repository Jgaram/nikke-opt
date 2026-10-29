# 실험 6 결과 — 분석 (analyze.py 생성)

**본 실행 전 — 형식만.** 기록이 없어 수치가 없다. 본 실행 뒤 관리자가 다시 만든다:

```bash
python experiments/06_control_menu/analyze.py experiments/06_control_menu/run_log/*.jsonl \
    --out experiments/06_control_menu/results.md
```

이 파일은 `analyze.py`가 만든다. 손으로 고치지 않는다. 해석과 최종 판단은 [README](README.md) 「결과」에 둔다.

## 지표 정의

입력은 실행 기록(`common.Record` JSON Lines)과 `compositions.json`뿐이다. `total_damage`가 없는(오류) 줄은 최선 계산에서 뺀다.

- **조건의 최선**: 조합 · 조건의 기록 중 총딜 최대. 동률이면 선택지 수가 적은 것, 그다음 step이 작은 것.
  `layer` · `auto` 조건 기록이 없으면 같은 바탕의 탐색 출발점(step 0, 선택지 없음)으로 대신한다.
- **이득 (잴 것 1)**: `search_from_layer` 최선 / `layer` − 1, / `auto` − 1. 분포는 최소 · 1사분위 · 중앙 · 3사분위 · 최대
  (사분위는 선형 보간, 표본 분위수 7형).
- **순위 상관 (잴 것 2)**: `auto` · `layer` · `search_from_layer` · `fixed_layer` 각 쌍에서 두 조건이 모두 있는 조합의
  최선 딜로 Spearman ρ(동순위는 평균 순위, 순위에 대한 Pearson). 상위 K개(동률은 comp_id 순)가 같은 집합인지와 겹친 수.
  **상위권 역전**: 두 조건에서 순서가 뒤집힌 조합 쌍 중 한쪽이라도 어느 조건에서 상위 K개에 드는 것.
- **니케 고유성 (잴 것 3)**: 조합마다 `search_from_layer` 최선 기록의 선택지에서 (니케, 축)의 label을 읽는다. 그 축의
  label이 없으면 「(바꾸지 않음)」. 그 조합 기록에 (니케, 축) 선택지가 한 번도 없으면 그 축은 메뉴에 없던 것으로 보고 세지 않는다.
  최빈 비율 = 최빈 선택을 고른 조합 수 / 그 니케 · 축이 있는 조합 수(최빈 동률은 「(바꾸지 않음)」, 그다음 label 순).
  **예외**는 최빈과 다른 선택을 한 조합이다. **예외 이득** = 예외 최선 딜 / (그 축만 최빈 선택으로 바꾼 선택지 집합의 딜) − 1.
  그 집합을 같은 조합 · 같은 바탕(layer 계열)에서 평가한 기록이 없으면 「미측정」.
  **동료 조건 후보** = 해당 예외 조합 모두에 있고 최빈 선택 조합에는 하나도 없는 동료(예외 label별, 그리고 예외 전체).
  스쿼드 단위 축(camera · tactic)은 니케 고유성에서 빼고 조합 표에만 보인다.
- **수렴 (잴 것 4)**: (조합, 탐색 조건, 출발점)마다 step 순으로 누적 최선이 기준 딜의 99.0% · 99.9%에
  처음 닿는 step과 그때까지(그 step 포함) `cached: false`인 줄 수(= 실제 시뮬). 기준 딜은 ① 그 실행의 마지막 최선,
  ② 그 조합의 모든 탐색 조건(`search_from_layer` · `search_from_auto` · `reference`) 최선. 닿지 못하면 「미도달」.
- **카메라 경합 (잴 것 5)**: `control_detail`(nikke-calc `docs/SIM-JSON.md` §결과에서 — `control_detail`, `23164e4`)의
  `preempted`(니케 → 카메라를 빼앗긴 횟수) · `overlap_t` · `max_concurrent`. 조합별 `search_from_layer` 최선 기록 값과,
  그 조합 전 기록에서 니케별 빼앗긴 횟수 합 · 빼앗긴 기록 수. 모르는 키는 따로 센다.
- **참조 차이**: `reference` 최선 / `search_from_layer` 최선 − 1.
- **실제 시뮬 수**: `cached: false`인 줄 수(조건별). 오류 줄도 센다.
- **판단 기준 표시**: 각 줄의 수치와 해당 여부. 수치 기준이 없는 줄(둘째 · 셋째)은 관련 수치만 보이고 「관리자 판단」으로 둔다.

## 기록

- 줄 0 (오류 0) · 조합 0 · 실제 시뮬(cached false) 0
- 조건별 줄: —
- 조건별 실제 시뮬: —

## 판단 기준 표시

수치는 인자(`--gain-median-max 0.01` · `--spearman-min 0.95` · `--top-k 5` · `--ref-gap-min 0.01`). 최종 판단은 관리자.

| 줄 | 기준 | 수치 | 해당 여부 |
|---|---|---|---|
| 1 | 탐색 이득 중앙 1% 미만 · Spearman 0.95 이상 · 상위 5개 유지 (layer ↔ search_from_layer) | gain_median — · spearman — · top_same — | 판정 불가 / 관리자 판단 |
| 2 | 니케 고유 선택이 대부분이고 예외를 동료 조건으로 설명할 수 있음 (수치 기준 없음 — 관리자 판단) | mode_share — · exceptions 0 · exceptions_with_peer_candidate 0 | 판정 불가 / 관리자 판단 |
| 3 | 예외가 잦고 동료 조건으로 설명되지 않음, 또는 순위 역전이 잦음 (수치 기준 없음 — 관리자 판단) | exceptions 0 · exceptions_without_peer_candidate 0 · top_reversals_layer_vs_search 0 | 판정 불가 / 관리자 판단 |
| 4 | 참조 탐색이 좌표 하강보다 1% 이상 좋음 (조합 하나라도) | ref_gap_max — · ref_gap_median — · n 0 | 판정 불가 / 관리자 판단 |

## 1. 탐색 이득

| 비교 | n | 최소 | 1사분위 | 중앙 | 3사분위 | 최대 |
|---|---|---|---|---|---|---|
| search_from_layer / layer − 1 | 0 | — | — | — | — | — |
| search_from_layer / auto − 1 | 0 | — | — | — | — | — |

| 조합 | 틀 | auto | layer | fixed_layer | search_from_layer | search_from_auto | reference | 이득 vs layer | 이득 vs auto | 참조 차이 |
|---|---|---|---|---|---|---|---|---|---|---|

조합별 `search_from_layer` 최선 선택:

| 조합 | 스쿼드 | 선택지 |
|---|---|---|

## 2. 조건 사이 순위 상관

| 조건 A | 조건 B | n | Spearman | 상위 5 겹침 | 같은 집합 | 상위권 역전 |
|---|---|---|---|---|---|---|
| auto | layer | 0 | — | 0 | — | 0 |
| auto | search_from_layer | 0 | — | 0 | — | 0 |
| auto | fixed_layer | 0 | — | 0 | — | 0 |
| layer | search_from_layer | 0 | — | 0 | — | 0 |
| layer | fixed_layer | 0 | — | 0 | — | 0 |
| search_from_layer | fixed_layer | 0 | — | 0 | — | 0 |

## 3. 니케 고유성

- (니케, 축) 0개 (조합 3개 이상: 0) · 관측 0 · 최빈 비율(전체) —
- 예외 0 (이득 측정 0 · 동료 조건 후보 있음 0)

| 예외 이득 | n | 최소 | 1사분위 | 중앙 | 3사분위 | 최대 |
|---|---|---|---|---|---|---|
| 예외 최선 / 최빈 적용 − 1 | 0 | — | — | — | — | — |

| 니케 | 축 | 조합 수 | 최빈 선택 | 최빈 비율 | 선택 분포 |
|---|---|---|---|---|---|

## 4. 수렴

탐색 기록 없음.

## 5. solo 카메라 경합

- 최선 기록에서 빼앗긴 조작이 있는 조합 0 · 어느 기록에서든 있는 조합 0 · `control_detail` 없는 줄 0

| 조합 | 최선 기록: 빼앗긴 횟수 | 최선 기록: 겹친 시간 · 최대 동시 | 전 기록: 니케별 빼앗긴 횟수 (기록 수) |
|---|---|---|---|

## 참조 탐색 대비

참조 조건 기록 없음.
