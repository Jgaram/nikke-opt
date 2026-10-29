# 실험 6 W2 — 니케별 컨트롤 선택지

[README §컨트롤 선택지](README.md#컨트롤-선택지-안)의 축을 니케 정보로 펼친 선택지 목록이다. 구현은 [menu.py](menu.py)
(`variants` · `apply` · `conflicts`), 니케 정보는 [nikke_info.json](nikke_info.json). 작성: W2 세션, 2026-10-29.

## 니케 정보의 출처

평가기 코드는 import하지 않는다. 공개 원본 `Jgaram/nikke-calc`의 **데이터 JSON만 읽기 전용으로** 써서
`nikke_info.json`을 뽑았고, 런타임에는 이 파일만 읽는다(nikke-calc 체크아웃 불필요).

| 항목 | 출처 (nikke-calc `23164e4a88fe46af609cc99b0de38a98313a5f4d`) |
|---|---|
| 무기 종류 · 차지 여부 · 차지 입력(UP · DOWN_Charge) · 풀차지 전용 · 버스트 단계 · 쿨 · 장탄 · 재장전 | `data/parsed_nikke.json` (`weapon_type` · `is_charge` · `input_type` · `full_charge_only` · `burst_stage` …) |
| 버스트 패턴 카탈로그 · 기본 레이어가 건드리는 축 | `data/char_defaults.json` (`_burst_patterns`, `control`과 `_rules[].apply.control`) |
| `charge_hold:N` 트리거 유무 (`hold_judge` 대상) | `data/parsed_skills.json` |
| 풀차지가 곧 버충인 니케(버충 담당 제외) | `docs/CONTROL.md` §버충 컨트롤 §담당 선택 — 헬름 · 맥스웰 : 오디너리 미케닉 · 스노우 화이트 : 헤비암즈 |

다시 뽑기(기존 `exclude`는 보존한다):

```bash
bash tools/setup_evaluators.sh --python   # /home/user/jgaram/nikke-calc 를 23164e4로 (Rust가 없으면 스크립트의 --python 부분을 손으로)
python experiments/06_control_menu/menu.py --extract /home/user/jgaram/nikke-calc
```

`layer` 칸은 그 니케의 기본 레이어가 어느 축을 건드리는지다 — `always`(무조건 `control`) · `rule`(`_rules`, 조건부).
조건(`with_member` · `atk_rank` 등)은 판정하지 않는다. 시험용 더미(`test_B1~3`)는 뺐다(203명).

## 축과 선택지

선택지에는 「바꾸지 않음」(출발점 그대로)이 없다. label은 `<니케 또는 squad>:<축>:<이름>`이고 니케 단위 선택지는
**스쿼드와 무관하게 같은 label · patch**다(니케 고유성 분석용). 니케 이름에 ` : `가 들어 있으므로 label을 `:`로 쪼개지
말고 `Variant`의 `nikke` · `axis` 칸을 쓴다.

| 축 | 대상 | 선택지(이름) | patch |
|---|---|---|---|
| `click` | 차지형 + `input_type: UP` (DOWN_Charge 6명 · 비차지 제외) | `auto` (레이어가 좌클릭을 건드리는 니케만) · `tap` · `hold_own_fb` · `hold_own_fb+tap` · `hold_judge` (`charge_hold` 보유자만 — 풀에는 없음). 풀차지 전용(홍련 : 흑영 · 레이븐)은 톡톡이가 안 돼 `hold_own_fb`만 | `control.click` 목록. `auto` = `click: false`(레이어 홀드·톡톡이까지 끈다) |
| `reload` | 전원 | `A0.3` · `B0.1` · `B0.5` · `C0.1` · `C0.5` · `C0.1_dry` | `control.reload.{policy, lead/margin, if_dry}` |
| `cover` | 전원 | `on` (레이어 무조건 엄폐가 아니면) · `off` (레이어가 엄폐를 거는 니케만 — 미하라 : 본딩 체인) | `control.cover` = `{policy: own_full_burst}` / `false`. 레이어 홀드가 있는 니케(에이다 · 아인)의 `on`은 `hold: false`를 함께 준다 |
| `cancel` | 전원 | `on` (레이어 무조건이 아니면) · `off` (레이어가 거는 니케만 — 홍련 : 흑영) | `control.reload.cancel_on_full` |
| `burst` | 버스트가 있는 니케(풀 전원) | `delay1` · `delay2` · `wait2` · `pattern=<이름>` (카탈로그가 있는 니케) · `pattern_off` (레이어가 패턴을 거는 니케) | `control.burst.{delay, wait_own_cooldown, pattern}` |
| `camera` (스쿼드) | 스쿼드의 차지형 전원(UP · DOWN_Charge) | 니케 이름 | `operation.camera` |
| `tactic` (스쿼드) | 톡톡이 가능한 차지형(풀차지 전용 · 풀차지 버충 니케 제외) — 평가기 `pick_burst_charge_carrier`의 후보 조건과 같다 | `버충=<니케>` | `operation.tactics = [{name: "버충", target}]` |

`variants(squad)`의 순서: 배치 순서대로 니케마다 click → reload → cover → cancel → burst, 그 뒤 camera → tactic.

### 값 격자

| 값 | 근거 |
|---|---|
| 톡톡이 `rate 3.6 · release 0.03` 한 값 | 레이어의 숙련 기준(`char_defaults.json` `_comment`, 앨리스 · 밀크). rate는 손 실력이라 운용 선택이 아니다 |
| 홀드 `lead 0.5`, `hold_judge` `lead 0.1` | 스키마 기본값 · 레이어 값(에이다 · 아인) · 권장값(CONTROL.md §click) |
| 장전컨 A `lead 0.3` 한 값 | 스키마 기본. CONTROL.md는 A를 상수 경로라 회귀 감지용으로만 남기고 실전은 C를 쓴다고 해 한 값만 둔다 |
| 장전컨 B `margin 0.1 · 0.5` | 0.1 = 기본. margin은 초 단위 절대값이라(§장전컨) 재장전이 긴 니케가 풀버스트 시작 버프(장탄 증가 등)를 확실히 받도록 0.5를 더한다 |
| 장전컨 C `margin 0.1 · 0.5`, C + `if_dry` `0.1` | 0.1 = 기본, 0.5 = 충전 창을 덜 먹는 여유. 실전 운용(§적용 조합 MG 셋)이 C + `if_dry`다. `if_dry`는 A · C(fb_end 앵커) 전용이라 B에는 없다 |
| 버스트 `delay 1 · 2`초 | 「0 · 몇 값」 — 문서 예시 2.0과 그 절반. 늦게 누르면 이후 사이클이 같이 밀리므로 큰 값은 두지 않았다 |
| `wait_own_cooldown 2`초 한 값 | 허용 범위 0.5~3초의 가운데 — README의 「끔 · 켬」 |
| 버스트 패턴 | 카탈로그 이름 그대로(미란다 · 츠바이 · 토브 `전담`, 마스트 `3의 배수` · `1,3,5,9,11,14`, 프리카 `첫 사이클만`) |

조합당 선택지는 니케 단위 평균 12.7개 × 5 + 카메라 · 버충 몇 개 ≈ **65~75개**다. 좌표 하강 한 바퀴가 이만큼이라
README 예산(조합당 100~200회)이면 두세 바퀴다.

## 조립 규칙

평가기가 조립 시점에 거절하거나 결과를 조용히 바꾸는 자리를 이렇게 다뤘다(Python 원본에서 짧은 시뮬로 확인).

| 자리 | 처리 |
|---|---|
| 같은 (니케, 축) 둘 | `apply`가 `ValueError` |
| 같은 니케의 `click` 홀드(`hold_own_fb` · `hold_own_fb+tap`) + `cover:on` | 평가기 오류(「같은 창(own_full_burst)에 엄폐컨과 홀드」, `invalid_input`). `conflicts()`가 잡고 `apply`가 **`MenuConflict`**(ValueError 하위)를 낸다 — 탐색은 이 조합을 시뮬하지 않고 건너뛰면 된다 |
| 레이어 홀드(에이다 + 미란다, 아인 + 에이다) + `cover:on` | 같은 오류가 레이어 쪽에서 난다. `cover:on` patch에 `hold: false`를 실어 피했다(`click` 선택지와 함께 줘도 평가기가 받는다) |
| `reload` 축과 `cancel` 축이 둘 다 `control.reload` | 잎 키가 겹치지 않아(policy · lead · margin · if_dry ↔ cancel_on_full) 재귀 병합으로 합친다. 병합 결과는 선택 순서와 무관하다 |
| `if_dry` + B(`into_fb`) | 평가기 오류(`next_fb_start` 앵커). 격자에 넣지 않았다 |
| 풀차지 전용에 톡톡이 · DOWN_Charge에 홀드 | 평가기 오류. 대상 규칙으로 만들지 않는다 |
| 카탈로그 없는 니케에 `pattern` 이름 | 평가기 오류. 카탈로그가 있는 니케만 |
| `tactic: 버충` + `camera` | 오류 없음. 버충 담당이 있으면 카메라는 담당으로 고정된다(CONTROL.md §버충 컨트롤은 모드와 무관하게 단독이다) — 둘을 같이 고르면 카메라 선택은 효과가 없다 |
| `tactic: 버충=X` + X의 `click` · `reload` | 오류 없음. 니케 `control`이 택틱보다 위라(SIM-JSON §control) X의 `click`이 택틱의 창 한정 톡톡이를 대체하고, `reload` 선택지가 택틱의 정책 C를 대체한다(재귀 병합이라 택틱의 `priority: high`는 남는 것으로 본다 — 확인하지 않았다) |

알려 둘 것:

- **레이어 조건은 판정하지 않는다.** `auto` · `off` · `pattern_off`는 그 니케의 레이어가 그 축을 건드릴 수 있으면 언제나 넣는다.
  조건이 안 맞는 스쿼드(예: 미란다 없는 에이다의 `click:auto`)에서는 출발점과 같은 결과가 한 번 더 나온다.
  `operation.auto: true`에서 출발하면 레이어가 없으므로 이 선택지들도 출발점과 같다.
- 레이어와 같은 값을 다시 주는 선택지(앨리스 `tap` 등)도 빼지 않았다. 결과는 출발점과 같다.
- `burst` 축은 딜레이 · 쿨 대기 · 패턴 중 **하나만** 고른다(한 축). 패턴 + 딜레이 같은 겹침은 이 메뉴 밖이다.
- 신데렐라 : 크리스탈 웨이브(재장전 3초 고정)의 장전컨, 아낄 버프가 없는 니케의 엄폐컨처럼 이득이 없어 보이는 것도
  README대로 지우지 않았다.
- 풀에 `charge_hold` 보유자가 없어 `hold_judge`는 이번 풀에서 한 번도 나오지 않는다(밀크 · 길티 · 신 · 라푼젤 · 크러스트가 대상).

## 조립 오류 검사

```bash
source .cache/evaluators.env && python experiments/06_control_menu/menu.py --check --json-out <scratchpad>/menu_check.jsonl
# 오류가 난 단독 선택지를 nikke_info.json exclude에 이유와 함께 싣는다(이후 variants에서 빠진다)
source .cache/evaluators.env && python experiments/06_control_menu/menu.py --check --write-exclude
```

니케마다 스쿼드 = 그 니케 + `미란다 · 크라운 · 헬름 · 리타 · 라피 : 레드 후드` 중 그 니케가 아닌 앞 4명(B1 · B2 · B3를 갖추고,
미란다로 에이다 · 미하라 레이어 규칙이 걸린다). 요청 = 기준(선택지 없음) 1 + 그 니케의 니케 단위 선택지 각 1 +
그 니케가 대상인 camera · tactic 각 1 + **모든 축 동시**(축마다 충돌하지 않는 첫 선택지) 1. 풀 60명에 **879개**.
`base` · `combo`의 오류는 exclude에 싣지 않는다 — 축 사이 상호작용이라 menu.py를 고칠 일이다.

### 결과

| 평가기 | 요청 | 실제 시뮬 | 오류 | 비고 |
|---|---|---|---|---|
| Python 원본 `23164e4` (W2 세션) | 11 | 11 | 0 | 위험한 자리만 골랐다: 에이다 `cover:on`(레이어 홀드 끄기) · 에이다 · 앨리스 `combo` · 미하라 `cover:off` · 홍련 `cancel:off` · `click:hold_own_fb` · 마스트 `pattern=3의 배수` · 프리카 `pattern_off` · `버충=에이다` · `camera:리버렐리오` · 라피 `C0.1_dry` |
| Rust `nikke-sim` (관리자) | 879 | — | — | 미실행 |

`exclude`: 없음(Rust 검사 후 갱신).

## 풀 60명의 선택지 표

`python experiments/06_control_menu/menu.py --table`로 만든다. reload는 6값 전부(`A0.3 · B0.1 · B0.5 · C0.1 · C0.5 · C0.1_dry`).
카메라 · 버충은 그 니케가 스쿼드 축의 대상이 될 수 있는지다. 수 = 니케 단위 선택지 + 카메라 · 버충 대상 수.

| 니케 | 무기 | 입력 | 버스트 | click | reload | cover | cancel | burst | 카메라 · 버충 | 수 |
|---|---|---|---|---|---|---|---|---|---|---|
| 라피 : 레드 후드 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 아니스 : 스타 | RL | DOWN_Charge · 풀차지 전용 | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 12 |
| 미란다 | SMG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 · pattern=전담 · pattern_off | — | 13 |
| D : 킬러 와이프 | SR | UP | 1 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 브리드 : 사일런트 트랙 | SG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 솔린 : 프로스트 티켓 | SG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 디젤 : 윈터 스위츠 | RL | UP | 3 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 리타 | SMG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 드레이크 | SG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 맥스웰 | SR | UP | 3 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 슈가 | SG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 미하라 : 본딩 체인 | MG | DOWN | 3 | — | 6값 | on · off | on | delay1 · delay2 · wait2 | — | 12 |
| 프리바티 | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 앨리스 | SR | UP | 3 | auto · tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 17 |
| 토브 | AR | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 · pattern=전담 · pattern_off | — | 13 |
| 루드밀라 : 윈터 오너 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 도라 | SR | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 나유타 | SMG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 홍련 : 흑영 | RL | UP · 풀차지 전용 | 3 | hold_own_fb | 6값 | on | off | delay1 · delay2 · wait2 | 카메라 | 13 |
| 도로시 : 세렌디피티 | SG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 모더니아 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 리버렐리오 | SR | DOWN_Charge · 풀차지 전용 | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 12 |
| 루주 | SR | UP | 1 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 목단 | AR | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 벨벳 | SR | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 마르차나 : 마린 스터디 | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 크라운 | MG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 헬름 | SR | UP | 3 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 15 |
| 헬름 : 아쿠아마린 | AR | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 마스트 : 로망틱 메이드 | MG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 · pattern=3의 배수 · pattern=1,3,5,9,11,14 · pattern_off | — | 14 |
| 앵커 : 이노센트 메이드 | RL | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 츠바이 | SG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 · pattern=전담 · pattern_off | — | 13 |
| 퀀시 : 이스케이프 퀸 | SMG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 플로라 | MG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 볼륨 | SMG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 나가 | SG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 레드 후드 | SR | UP | A | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 스노우 화이트 : 헤비암즈 | SR | UP | 3 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 15 |
| 일레그 : 붐 앤 쇼크 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 신데렐라 | RL | DOWN_Charge · 풀차지 전용 | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 12 |
| 리틀 머메이드 | SMG | DOWN | 1 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 그레이브 | AR | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 신데렐라 : 크리스탈 웨이브 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 브래디 | SR | UP | 3 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 아크레인저 블랙 | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 아르카나 : 포츈 메이트 | SG | DOWN | 2 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 민트 | RL | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 프리카 | SR | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 · pattern=첫 사이클만 · pattern_off | 카메라 · 버충 | 18 |
| 2B | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 아스카 | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 레이 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 레이 (가칭) | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 아스카 : WILLE | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 에이다 | RL | UP | 3 | auto · tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 17 |
| 이브 | AR | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 레이븐 | RL | UP · 풀차지 전용 | 3 | hold_own_fb | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 | 13 |
| 치사토 | SMG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 타키나 | SR | UP | 2 | tap · hold_own_fb · hold_own_fb+tap | 6값 | on | on | delay1 · delay2 · wait2 | 카메라 · 버충 | 16 |
| 퀸(마코토) | SG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |
| 유키코 | MG | DOWN | 3 | — | 6값 | on | on | delay1 · delay2 · wait2 | — | 11 |

60명, 선택지 합계 759 (니케당 평균 12.7)
