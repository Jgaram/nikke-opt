# 실험 6 조합 선정 (W3)

`select_comps.py`가 쓴다 — 손으로 고치지 않는다. 형식은 `common.Composition`, 목록은 [`compositions.json`](compositions.json).

## 방법

규칙은 [README §평가 문제](README.md#평가-문제--조합-약-30개), 구현은 [`select_comps.py`](select_comps.py)(docstring에 전체 규칙).
컨트롤 결과를 보기 전에 정한 고정 규칙이다(시드 `20261029`).

| 단계 | 내용 |
|---|---|
| 출처 | 실험 2 [`pool.json`](../02_score_distribution/pool.json)(풀 60명 · 버스트 단계) · [`ranker_squads.json`](../02_score_distribution/ranker_squads.json)(S40 랭커 순서 구분 스쿼드 224개 → 구성 66개) |
| 니케 정보 | Jgaram/nikke-calc 23164e4 (data/parsed_nikke.json · data/weapon_delays.json)에서 읽기 전용으로 뽑아 `NIKKE_INFO`에 넣었다: 무기 · 차지형(`is_charge`) · 입력 방식 · 풀차지 전용 · 정적 게이지 속도 |
| 후보 ① | 랭커 구성 66개, 배치 순서는 그 구성의 랭커 최빈 순서 |
| 후보 ② | 랭커 구성(덱 수순)의 한 자리를 같은 버스트 단계 풀 니케로 교체(자리 그대로). 레이어 대상 9명은 니케당 12개, 레드 후드 24개(랭커가 쓰지 않아 그 틀은 교체로만 생긴다), 나머지 3개까지. 레드 후드는 B2·B3 자리에 넣어 (1,1,2)+A · (2,1,1)+A 틀. 에이다는 미란다 구성부터 |
| 평가 | 후보 전부를 기본 레이어(운용 없음) + `accumulate`(어댑터 기본 sim) + 기본 적으로 1회씩 |
| 성능 구간 | 버스트 틀마다 딜 순 3등분 → 상 · 중만 남긴다(레드 후드 틀이 전체 분포에서 약해 틀마다 나눔) |
| 할당 | 틀별 1-1-3 9, 1-2-2 8, 2-1-2 7, redhood 6 (합 30) |
| 씨앗 | 레이어 대상 9명마다 그 니케가 든 후보를 아래 점수로 골라 3개 조합까지 먼저 넣는다 |
| 탐욕 선정 | 점수 = 등장 1~2회 니케 +2 · 처음 나오는 니케 −1 · 3회 미만 레이어 대상 +3 · 첫 미란다+에이다/미하라 +3 · 틀 안 상·중 균형 +1.5 · 틀 안 레이어 대상 포함/미포함 균형(절반 전 +1.5, 절반 이후 −4) · 랭커 구성 +1 · 차지형 수 구간 다양성 1/(1+n) · base 충전 추정 구간 다양성 1/(1+n). 동점은 시드 고정 순서 |
| 수리 | 등장 3회 미만 니케 → 새 니케 없는 후보 추가(최대 32개, 틀 할당 +1까지) → 안 되면 같은 틀 조합과 맞바꿈 → 그래도 안 되면 그 니케의 조합 제외. 28개 미만이면 새 니케 없는 후보로 채움 |

**태그** — `band:high|mid` · `ranker|swap` · `layer_target`(+`layer:<니케>`) 또는 `no_layer_target` · `miranda_rule`(미란다 +
에이다/미하라 — 그 레이어가 붙는 조건) · 차지형 수 `charge_none|light|mid|heavy`(0 · 1 · 2 · 3명 이상) + `charge_n:<k>` ·
base 충전 추정 3등분 `gauge_fast|mid|slow` · `charger_candidate`(톡톡이가 되는 차지형이 있음 = 버충 담당 후보).

**한계** — base 충전 추정은 무기 사격만의 정적 값이다(스킬 충전 · 풀차지 배율 · 카메라 제외). 실제 base 충전 시간은 시뮬
결과인데 평가기 결과에 나오지 않아, 후보 사이 상대 순위로만 쓴다. 앨리스의 레이어(톡톡이)는 차지속도 옵션 8.18% 이상일 때만
붙는데, 기본 스펙에서 붙는 것을 원본(Python `23164e4`)으로 확인했다(`spec.char_defaults.applied`, 미란다 + 에이다 · 미하라도 붙음). 레이어가 붙는 니케 중 아인 · 밀크 : 블루밍
바니 · 길티 : 마이티 바니 · 신 : 스위프트 바니 · 라푼젤 : 퓨어 그레이스는 풀에 없어 넣지 않았다. 교체 후보는 랭커 구성에서 한
명만 바꾼 것이라 랭커 구성 근처에 몰려 있다(실험 2 §1: 무작위 스쿼드는 랭커 구성보다 훨씬 약하다).

## 후보

후보 348개 (랭커 구성 66 · 한 명 교체 282). 할당 밖 틀(`없음`)은 선정에서 뺀다.

| 틀 | 랭커 | 교체 |
|---|---|---|
| 1-1-3 | 34 | 88 |
| 1-2-2 | 22 | 107 |
| 2-1-2 | 10 | 63 |
| redhood | 0 | 24 |

## 평가

| | |
|---|---|
| 평가기 | `{"repo": "nikke-calc-rs", "commit": "89d2e64406dc60592ba90cb71935b7d56154ed52", "dirty": false, "port_of": {"repo": "Jgaram/nikke-calc", "commit": "23164e4a88fe46af609cc99b0de38a98313a5f4d"}}` |
| 요청 | 348개 (기본 레이어 · accumulate · 기본 적) |
| **실제 시뮬** | **347회** (캐시 적중 1) |
| 오류 | 0개 |
| 상·중 후보 | 234개 |

### 성능 구간 (틀별, 억)

| 틀 | 후보 | 최대 | 상 하한 | 중 하한 | 최소 |
|---|---|---|---|---|---|
| 1-1-3 | 122 | 44.8 | 31.6 | 21.9 | 6.9 |
| 1-2-2 | 129 | 46.1 | 29.7 | 25.4 | 8.5 |
| 2-1-2 | 73 | 36.5 | 27.5 | 22.6 | 9.3 |
| redhood | 24 | 32.9 | 23.5 | 19.4 | 7.8 |

## 선정 과정

씨앗 · 탐욕 단계(순번:후보(점수), 씨앗은 [대상]): 1:k055(7.0)[앨리스] · 2:k241(17.0)[앨리스] · 3:k022(10.0)[앨리스] · 4:k263(14.67)[에이다] · 5:k253(16.75)[에이다] · 6:k257(19.53)[에이다] · 7:k011(19.5)[미하라 : 본딩 체인] · 8:k182(12.83)[미하라 : 본딩 체인] · 9:k338(7.0)[홍련 : 흑영] · 10:k346(8.42)[홍련 : 흑영] · 11:k339(12.14)[홍련 : 흑영] · 12:k149(12.32)[마스트 : 로망틱 메이드] · 13:k276(10.33)[츠바이] · 14:k284(8.75)[츠바이] · 15:k277(4.81)[츠바이] · 16:k097(1.5)[토브] · 17:k117(13.34)[토브] · 18:k021(11.95)[토브] · 19:k098(7.29) · 20:k015(5.6) · 21:k008(5.42) · 22:k089(5.31) · 23:k104(5.25) · 24:k038(5.18) · 25:k042(6.31) · 26:k064(5.22) · 27:k114(5.21) · 28:k102(3.42) · 29:k139(4.29) · 30:k166(3.75)

수리: 그레이브 1→2회: k058 추가; 그레이브 2→3회: k073 추가; 플로라 2→3회: k055 → k047 교체

규칙 점검: **통과**

## 조합

| id | 틀 | 배치 순서 | 기본 레이어 딜(억) | 구간 | 차지형 | 충전 추정(초) | 태그 | 출처 |
|---|---|---|---|---|---|---|---|---|
| c01 | 1-1-3 | 아니스 : 스타 · 브리드 : 사일런트 트랙 · 홍련 : 흑영 · 디젤 : 윈터 스위츠 · 프리바티 | 43.8 | high | 3 | 6.68 | swap layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:61 라피 : 레드 후드→홍련 : 흑영 [후보 k346] |
| c02 | 1-1-3 | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 아니스 : 스타 · 드레이크 · 프리바티 | 40.5 | high | 1 | 3.67 | swap no_layer_target charge_light gauge_fast | swap:ranker:2 미하라 : 본딩 체인→드레이크 [후보 k089] |
| c03 | 1-1-3 | 나유타 · 아니스 : 스타 · 라피 : 레드 후드 · 프리바티 · 모더니아 | 38.0 | high | 1 | 5.62 | ranker no_layer_target charge_light gauge_slow | ranker:136 (덱 1) [후보 k038] |
| c04 | 1-1-3 | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 아니스 : 스타 · 미하라 : 본딩 체인 · 홍련 : 흑영 | 33.4 | high | 2 | 5.76 | swap layer_target charge_mid gauge_slow | swap:ranker:2 프리바티→홍련 : 흑영 [후보 k339] |
| c05 | 1-1-3 | 목단 · 나유타 · 스노우 화이트 : 헤비암즈 · 신데렐라 : 크리스탈 웨이브 · 모더니아 | 31.6 | high | 1 | 5.17 | ranker no_layer_target charge_light gauge_mid charger_candidate | ranker:214 (덱 1) [후보 k064] |
| c06 | 1-1-3 | 크라운 · 퀸(마코토) · 리틀 머메이드 · 유키코 · 모더니아 | 29.4 | mid | 0 | 4.78 | ranker no_layer_target charge_none gauge_mid | ranker:151 (덱 1) [후보 k042] |
| c07 | 1-1-3 | 리타 · 그레이브 · 스노우 화이트 : 헤비암즈 · 신데렐라 : 크리스탈 웨이브 · 모더니아 | 28.9 | mid | 1 | 4.21 | ranker no_layer_target charge_light gauge_fast charger_candidate | ranker:198 (덱 1) [후보 k058] |
| c08 | 1-1-3 | 크라운 · 앨리스 · 목단 · 유키코 · 프리바티 | 25.4 | mid | 1 | 5.22 | ranker layer_target charge_light gauge_mid charger_candidate | ranker:124 (덱 2) [후보 k022] |
| c09 | 1-1-3 | 브리드 : 사일런트 트랙 · 라피 : 레드 후드 · 츠바이 · 미하라 : 본딩 체인 · 프리바티 | 23.8 | mid | 0 | 3.97 | swap layer_target charge_none gauge_fast | swap:ranker:2 아니스 : 스타→츠바이 [후보 k276] |
| c10 | 1-1-3 | 마스트 : 로망틱 메이드 · 라피 : 레드 후드 · 아니스 : 스타 · 미하라 : 본딩 체인 · 프리바티 | 23.3 | mid | 1 | 5.56 | swap layer_target charge_light gauge_slow | swap:ranker:2 브리드 : 사일런트 트랙→마스트 : 로망틱 메이드 [후보 k149] |
| c11 | 1-2-2 | 목단 · 브리드 : 사일런트 트랙 · 스노우 화이트 : 헤비암즈 · 플로라 · 디젤 : 윈터 스위츠 | 35.9 | high | 2 | 5.56 | ranker no_layer_target charge_mid gauge_slow charger_candidate | ranker:80 (덱 3) [후보 k015] |
| c12 | 1-2-2 | 크라운 · 유키코 · 리틀 머메이드 · 미하라 : 본딩 체인 · 마스트 : 로망틱 메이드 | 33.8 | high | 0 | 5.00 | swap layer_target charge_none gauge_mid | swap:ranker:3 퀸(마코토)→미하라 : 본딩 체인 [후보 k182] |
| c13 | 1-2-2 | 리타 · 브리드 : 사일런트 트랙 · 스노우 화이트 : 헤비암즈 · 플로라 · 디젤 : 윈터 스위츠 | 33.3 | high | 2 | 5.86 | ranker no_layer_target charge_mid gauge_slow charger_candidate | ranker:166 (덱 1) [후보 k047] |
| c14 | 1-2-2 | 목단 · 나유타 · 스노우 화이트 : 헤비암즈 · 플로라 · 디젤 : 윈터 스위츠 | 32.5 | high | 2 | 5.93 | ranker no_layer_target charge_mid gauge_slow charger_candidate | ranker:13 (덱 26) [후보 k008] |
| c15 | 1-2-2 | 크라운 · 유키코 · 리틀 머메이드 · 홍련 : 흑영 · 마스트 : 로망틱 메이드 | 31.1 | high | 1 | 5.38 | swap layer_target charge_light gauge_mid | swap:ranker:3 퀸(마코토)→홍련 : 흑영 [후보 k338] |
| c16 | 1-2-2 | 츠바이 · 민트 · 스노우 화이트 : 헤비암즈 · 디젤 : 윈터 스위츠 · 프리카 | 29.2 | mid | 4 | 5.60 | swap layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:7 목단→츠바이 [후보 k277] |
| c17 | 1-2-2 | 목단 · 민트 · 스노우 화이트 : 헤비암즈 · 앨리스 · 프리카 | 28.6 | mid | 4 | 6.68 | swap layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:7 디젤 : 윈터 스위츠→앨리스 [후보 k241] |
| c18 | 1-2-2 | 목단 · 민트 · 에이다 · 디젤 : 윈터 스위츠 · 프리카 | 27.9 | mid | 4 | 7.82 | swap layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:7 스노우 화이트 : 헤비암즈→에이다 [후보 k263] |
| c19 | 2-1-2 | 토브 · 드레이크 · 아르카나 : 포츈 메이트 · 퀸(마코토) · 솔린 : 프로스트 티켓 | 34.0 | high | 0 | 3.29 | ranker layer_target charge_none gauge_fast | ranker:123 (덱 2) [후보 k021] |
| c20 | 2-1-2 | 츠바이 · 크라운 · 미하라 : 본딩 체인 · 프리바티 · 리틀 머메이드 | 30.1 | high | 0 | 4.10 | swap layer_target charge_none gauge_fast | swap:ranker:36 미란다→츠바이 [후보 k284] |
| c21 | 2-1-2 | 토브 · 그레이브 · 도로시 : 세렌디피티 · 드레이크 · 솔린 : 프로스트 티켓 | 27.7 | high | 0 | 2.85 | swap layer_target charge_none gauge_fast | swap:ranker:0 아르카나 : 포츈 메이트→그레이브 [후보 k073] |
| c22 | 2-1-2 | 미란다 · 크라운 · 미하라 : 본딩 체인 · 프리바티 · 리틀 머메이드 | 27.2 | mid | 0 | 5.07 | ranker layer_target miranda_rule charge_none gauge_mid | ranker:36 (덱 13) [후보 k011] |
| c23 | 2-1-2 | 미란다 · 크라운 · 에이다 · 프리바티 · 리틀 머메이드 | 27.1 | mid | 1 | 5.76 | swap layer_target miranda_rule charge_light gauge_slow charger_candidate | swap:ranker:36 미하라 : 본딩 체인→에이다 [후보 k253] |
| c24 | 2-1-2 | 미란다 · 크라운 · 에이다 · 미하라 : 본딩 체인 · 리틀 머메이드 | 27.0 | mid | 1 | 5.76 | swap layer_target miranda_rule charge_light gauge_slow charger_candidate | swap:ranker:160 헬름→에이다 [후보 k257] |
| c25 | 2-1-2 | 리타 · 아르카나 : 포츈 메이트 · 도로시 : 세렌디피티 · 드레이크 · 솔린 : 프로스트 티켓 | 22.7 | mid | 0 | 3.32 | swap no_layer_target charge_none gauge_fast | swap:ranker:0 토브→리타 [후보 k139] |
| c26 | 2-1-2 | 목단 · 아르카나 : 포츈 메이트 · 도로시 : 세렌디피티 · 드레이크 · 솔린 : 프로스트 티켓 | 22.6 | mid | 0 | 3.23 | swap no_layer_target charge_none gauge_fast | swap:ranker:0 토브→목단 [후보 k166] |
| c27 | redhood | 크라운 · 유키코 · 리틀 머메이드 · 퀸(마코토) · 레드 후드 | 24.4 | high | 1 | 4.98 | swap no_layer_target charge_light gauge_mid charger_candidate | swap:ranker:3 마스트 : 로망틱 메이드→레드 후드 [후보 k098] |
| c28 | redhood | 토브 · 아르카나 : 포츈 메이트 · 레드 후드 · 드레이크 · 솔린 : 프로스트 티켓 | 23.9 | high | 1 | 3.47 | swap layer_target charge_light gauge_fast charger_candidate | swap:ranker:0 도로시 : 세렌디피티→레드 후드 [후보 k097] |
| c29 | redhood | 목단 · 나유타 · 스노우 화이트 : 헤비암즈 · 레드 후드 · 디젤 : 윈터 스위츠 | 23.6 | high | 3 | 6.20 | swap no_layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:13 플로라→레드 후드 [후보 k104] |
| c30 | redhood | 목단 · 스노우 화이트 : 헤비암즈 · 민트 · 레드 후드 · 신데렐라 : 크리스탈 웨이브 | 22.0 | mid | 3 | 6.08 | swap no_layer_target charge_heavy gauge_slow charger_candidate | swap:ranker:155 프리카→레드 후드 [후보 k114] |
| c31 | redhood | 토브 · 레드 후드 · 아르카나 : 포츈 메이트 · 퀸(마코토) · 솔린 : 프로스트 티켓 | 20.9 | mid | 1 | 4.72 | swap layer_target charge_light gauge_mid charger_candidate | swap:ranker:123 드레이크→레드 후드 [후보 k117] |
| c32 | redhood | 리타 · 그레이브 · 앨리스 · 신데렐라 : 크리스탈 웨이브 · 레드 후드 | 19.4 | mid | 2 | 4.45 | swap layer_target charge_mid gauge_fast charger_candidate | swap:ranker:6 모더니아→레드 후드 [후보 k102] |

## 니케별 등장 조합 수

| 니케 | 단계 | 조합 수 | 레이어 대상 | 차지형 | 조합 |
|---|---|---|---|---|---|
| 목단 | 1 | 9 |  |  | c05 c08 c11 c14 c17 c18 c26 c29 c30 |
| 스노우 화이트 : 헤비암즈 | 3 | 9 |  | ○ | c05 c07 c11 c13 c14 c16 c17 c29 c30 |
| 크라운 | 2 | 9 |  |  | c06 c08 c12 c15 c20 c22 c23 c24 c27 |
| 프리바티 | 3 | 9 |  |  | c01 c02 c03 c08 c09 c10 c20 c22 c23 |
| 리틀 머메이드 | 1 | 8 |  |  | c06 c12 c15 c20 c22 c23 c24 c27 |
| 디젤 : 윈터 스위츠 | 3 | 7 |  | ○ | c01 c11 c13 c14 c16 c18 c29 |
| 미하라 : 본딩 체인 | 3 | 7 | ○ |  | c04 c09 c10 c12 c20 c22 c24 |
| 드레이크 | 3 | 6 |  |  | c02 c19 c21 c25 c26 c28 |
| 레드 후드 | A | 6 |  | ○ | c27 c28 c29 c30 c31 c32 |
| 브리드 : 사일런트 트랙 | 2 | 6 |  |  | c01 c02 c04 c09 c11 c13 |
| 솔린 : 프로스트 티켓 | 1 | 6 |  |  | c19 c21 c25 c26 c28 c31 |
| 라피 : 레드 후드 | 3 | 5 |  |  | c02 c03 c04 c09 c10 |
| 아니스 : 스타 | 1 | 5 |  | ○ | c01 c02 c03 c04 c10 |
| 아르카나 : 포츈 메이트 | 2 | 5 |  |  | c19 c25 c26 c28 c31 |
| 유키코 | 3 | 5 |  |  | c06 c08 c12 c15 c27 |
| 나유타 | 2 | 4 |  |  | c03 c05 c14 c29 |
| 리타 | 1 | 4 |  |  | c07 c13 c25 c32 |
| 모더니아 | 3 | 4 |  |  | c03 c05 c06 c07 |
| 민트 | 2 | 4 |  | ○ | c16 c17 c18 c30 |
| 신데렐라 : 크리스탈 웨이브 | 3 | 4 |  |  | c05 c07 c30 c32 |
| 퀸(마코토) | 3 | 4 |  |  | c06 c19 c27 c31 |
| 토브 | 1 | 4 | ○ |  | c19 c21 c28 c31 |
| 그레이브 | 2 | 3 |  |  | c07 c21 c32 |
| 도로시 : 세렌디피티 | 3 | 3 |  |  | c21 c25 c26 |
| 마스트 : 로망틱 메이드 | 2 | 3 | ○ |  | c10 c12 c15 |
| 미란다 | 1 | 3 | ○ |  | c22 c23 c24 |
| 앨리스 | 3 | 3 | ○ | ○ | c08 c17 c32 |
| 에이다 | 3 | 3 | ○ | ○ | c18 c23 c24 |
| 츠바이 | 1 | 3 | ○ |  | c09 c16 c20 |
| 프리카 | 2 | 3 | ○ | ○ | c16 c17 c18 |
| 플로라 | 2 | 3 |  |  | c11 c13 c14 |
| 홍련 : 흑영 | 3 | 3 | ○ | ○ | c01 c04 c15 |

## 태그 분포

`band:high` 16 · `band:mid` 16 · `charge_heavy` 6 · `charge_light` 12 · `charge_mid` 5 · `charge_none` 9 · `charger_candidate` 18 · `gauge_fast` 10 · `gauge_mid` 8 · `gauge_slow` 14 · `layer_target` 19 · `miranda_rule` 3 · `no_layer_target` 13 · `ranker` 10 · `swap` 22
