# 실험 6 세션 계획 — 관리자 세션과 작업 세션

[실험 6](README.md)은 다음 세션이 **관리자**가 되어 여러 **작업 세션**을 열어 진행한다(2026-10-29 사용자 결정).
공통 운영 규칙은 [작업 규칙 §여러 세션으로 진행할 때](../../rules/workflow.md#여러-세션으로-진행할-때)이고, 이 문서는 실험 6의 구체 계획이다.
이 문서와 README는 관리자만 고친다.

## 역할

| 세션 | 하는 일 |
|---|---|
| **관리자** (다음 세션) | 이 문서대로 실험 6을 끝까지 운영한다. 인터페이스 골격 커밋, 작업 세션 생성·지시·확인, 통합 검증, 시운전·본 실행, 해석·판단, README 결과·ROADMAP 갱신, 다음 회차 계획 초안, 사용자 보고 |
| **작업 세션** W1~W5 | 관리자가 `create_session`으로 연다. 맡은 파일만 고치고 `main`에 push한 뒤 관리자에게 `send_message`로 보고한다. 다른 세션을 열지 않는다 |

다음 회차의 **구현 착수**는 관리자가 결과와 다음 계획을 보고한 뒤 사용자 확인을 받고 한다.

## 0. 관리자가 작업 세션을 열기 전에

1. **평가기 준비** — 관리자 세션에 `Jgaram/nikke-calc-rs`가 붙어 있어야 한다(세션을 열 때 고르거나 `add_repo`).
   `bash tools/setup_evaluators.sh`로 빌드하고 `source .cache/evaluators.env && python -m nikke_opt.eval "크라운"`으로 확인한다.
2. **작업 세션의 평가기 접근 확인** — `create_session`은 레포 하나(`source_url` = nikke-opt)로 연다.
   nikke-calc-rs는 환경 '전체'의 Repositories에 있으면 같이 받고, 없으면 작업 세션이 `add_repo`로 붙인다.
   W1을 먼저 열어 붙이기·빌드가 되는지 확인한다. 안 되면 평가기가 필요한 단계(W1 · W2의 검증 · W3의 후보 평가 · 본 실행)는
   관리자가 직접 돌리고, 작업 세션은 가짜 평가기 테스트까지 맡는다.
   - **확인 결과(2026-10-29):** 작업 세션의 `add_repo(nikke-calc-rs)`가 권한 분류기에서 거부됐다(W1). 그래서 대안대로
     Rust 실행(W1 대조 · W2 조립 검사 · W3 후보 평가 · W4 실제 연결 확인 · 본 실행)은 관리자가 돌리고, 작업 세션은
     실행 명령을 갖춘 코드와 가짜 평가기 테스트까지 맡는다. 공개 원본 nikke-calc(Python)는 작업 세션에서도 받을 수 있다.
     작업 세션 id: W1 `session_01MQimn4hFKotwTSPxUWqsaJ` · W2 `session_01MQimn3sWvuYAcbFCbd1S55` ·
     W3 `session_01MQimn59m22mixwayR65jck` · W4 `session_01MQimn5a2Xs4gP1dCmze9UW` · W5 `session_01MQimn1VGRcf1w14wEB38e6`.
3. **인터페이스 골격 커밋** — 아래 「인터페이스」의 함수·형식을 빈 구현(또는 `NotImplementedError`)과 docstring으로 먼저 커밋한다.
   작업 세션은 이 골격을 기준으로 병렬로 개발한다.

## 파일 소유

| 경로 (`experiments/06_control_menu/` 기준) | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `common.py`(공용 형식) · `tests/test_exp06_skeleton.py` · `run_log/`(본 실행 출력) | 관리자 |
| `crosscheck.py` · `crosscheck.md` | W1 |
| `menu.py` · `menu.md` · `tests/test_exp06_menu.py`(레포 루트 `tests/`) | W2 |
| `select_comps.py` · `compositions.json` · `selection.md` · `tests/test_exp06_select.py` | W3 |
| `search.py` · `tests/test_exp06_search.py` | W4 |
| `analyze.py` · `results.md` · `tests/test_exp06_analyze.py` | W5 |
| `docs/` · `README.md`(레포) · `rules/` · `AGENTS.md` · `nikke_opt/` | 관리자. 작업 세션이 바꿔야 하면 관리자에게 알린다 |

## 인터페이스 (골격으로 고정할 것)

골격은 커밋되어 있다 — 형식의 정본은 `common.py`, 함수 계약은 각 모듈의 docstring이다.
`select.py` 대신 `select_comps.py`를 쓴다(표준 모듈 `select`를 가려 `subprocess`가 깨진다).


- **선택지** `Variant` = `{"nikke": 이름 | null(스쿼드 단위), "axis": "click" | "reload" | "cover" | "cancel" | "burst" | "camera" | "tactic", "label": str, "patch": 요청 options 조각}`.
  `patch`는 `{"chars": {니케: {"control": {...}}}}` 또는 `{"operation": {...}}` 꼴이다.
- `menu.variants(squad) -> dict[(nikke, axis), list[Variant]]` — 축마다 「바꾸지 않음」을 뺀 선택지.
- `menu.apply(options, variants) -> options` — 기본 options 위에 선택지들을 병합한다. 같은 (니케, 축)은 하나만.
- **조합 목록** `compositions.json` = `[{"id", "squad": [배치 순서], "skeleton": "1-1-3" 등, "tags": [...], "source", "default_damage"}]`.
- **실행 기록** JSON Lines 한 줄 = `{"comp_id", "condition", "start", "step", "variants": [label...], "request", "total_damage",
  "control_detail", "cached", "error", "evaluator", "sim_count"}`. 조건 이름: `auto` · `layer` · `search_from_layer` ·
  `search_from_auto` · `reference` · `fixed_layer`.

## 작업 묶음

| ID | 내용 | 평가기 | 선행 | 완료 조건 |
|---|---|---|---|---|
| **W1** 평가기 대조 | Rust ↔ Python 원본(`23164e4`) 대조. 기본 적에서 조합 3~4개 × `accumulate` · `solo` · 축별 컨트롤 · 완전 오토 · 버충 · 카메라를 덮는 요청 15~20개 | Rust + Python(`--python`) | 0 | `crosscheck.md`에 요청별 상대 차이 표. 1% 이상(임시) 차이 나는 축은 원인 후보와 함께 표시 |
| **W2** 선택지 생성 | 니케 정보(무기 종류 · 차지 입력 UP/DOWN · 버스트 단계 · 패턴 카탈로그)의 출처를 정하고 `menu.variants` 구현. 평가기 데이터를 읽기 전용으로 쓰면 출처 커밋을 남긴다(평가기 코드 import 금지). 선택지마다 한 번 요청해 조립 오류가 나는 것은 이유와 함께 뺀다 | Rust (검증) | 0 | 풀 60명의 선택지 표 `menu.md`, 테스트 통과 |
| **W3** 조합 선정 | [README §평가 문제](README.md#평가-문제--조합-약-30개) 규칙으로 약 30개. 후보를 기본 레이어 + `accumulate`로 평가해(수백 회 이내) 성능 구간을 정한다. 배치 순서는 랭커 최빈 순서 | Rust | 0 | `compositions.json` · `selection.md`(규칙 적용 과정, 니케별 등장 조합 수). 사용한 시뮬 수 |
| **W4** 탐색 실행기 | 여섯 조건 실행, 좌표 하강(니케·축 하나씩, 개선 없을 때까지), 참조(무작위 재시작), 예산·기록, 중단 후 재개 | 가짜 평가기 | 0 | 가짜 평가기 테스트 통과. W2 완료 후 실제 `menu`와 연결해 조합 하나로 동작 확인 |
| **W5** 분석 | [README §잴 것](README.md#잴-것) 1~5를 계산해 `results.md`로. 니케 고유성은 니케·축별 최빈 선택 비율과 예외(다른 선택의 이득 크기 · 동료 조건) | 없음 | 0 | 가짜 기록으로 테스트 통과 |

W1~W5는 동시에 연다. 각 작업의 세부 판단은 작업 세션이 하고 근거를 자기 문서에 남긴다.

## 관리자 점검 시점

1. **W1 보고** — 크게 다른 축이 있으면 그 축을 빼거나, 그 축만 원본으로 돌리거나, 둘 다 기록하고 진행할지 정해 README에 남긴다.
2. **W2 · W3 보고** — 선택지 표와 조합 목록이 README의 규칙대로인지(같은 니케가 3개 조합 이상) 확인한다.
3. **실행 전** — 판단 기준 수치를 README에 확정해 커밋한다(사전 등록). 실행 뒤 바꾸면 원래 값과 이유를 함께 남긴다.
4. **시운전** — 조합 3개로 조합당 시뮬 수 · 오류 · 기록을 확인하고 예산을 다시 추정한다.
5. **본 실행** — 관리자 세션 한 곳에서 돌려 시뮬 횟수를 한 번에 센다. 출력은 실행 중 scratchpad에 쓰고 끝나면 `run_log/`로 옮긴다.
6. **결과** — W5의 분석을 돌려 README 「결과」와 판단 표의 선택을 쓰고, ROADMAP 현재 상태·다음 행동과 다음 회차 계획 초안을 갱신한 뒤 사용자에게 보고한다.

## 작업 세션 지시 (create_session `prompt` 틀)

```text
너는 nikke-opt 실험 6의 작업 세션 <ID>다. 관리자 세션은 <관리자 session_id>다.
1. AGENTS.md와 rules/workflow.md를 읽고 따른다. main에서 작업하고 main에 push한다.
2. experiments/06_control_menu/SESSIONS.md의 <ID> 항목과 README.md를 읽는다.
3. 맡은 파일: <파일 목록>. 다른 파일은 고치지 않는다. 고쳐야 하면 관리자에게 알린다.
4. 평가기가 필요하면 Jgaram/nikke-calc-rs를 이 세션에 붙이고 `bash tools/setup_evaluators.sh`(W1은 `--python`)를 실행한다.
   붙이거나 빌드할 수 없으면 우회하지 말고 바로 관리자에게 알린다.
5. 끝나면 테스트 → 커밋 → push 후 관리자에게 send_message로 보고한다:
   커밋 해시, 테스트 결과(통과·실패·생략), 실제 시뮬 횟수, 판단한 것과 근거, 남은 문제.
```

`permission_mode`는 관리자 설정을 물려받고 `plan`은 쓰지 않는다(승인을 기다리며 멈춘다).
보고가 오지 않으면 `get_session`(`status_bucket`)과 `list_events`로 확인하고, 반영이 끝난 작업 세션은 `archive_session`으로 닫는다.

## 사용자 준비 (있으면 편함)

- 다음 세션을 열 때 nikke-opt와 nikke-calc-rs를 함께 고른다.
- 작업 세션이 nikke-calc-rs를 바로 받게 하려면 환경 '전체' 설정(세션 제목 줄의 환경 메뉴 → Edit)의 Repositories에 nikke-calc-rs를 추가한다.
