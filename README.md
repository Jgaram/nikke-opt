# nikke-opt

승리의 여신: 니케 솔로 레이드 조합 최적화기.
새 계정·상황, 신캐 추가, 새 보스 패턴에서도 적은 시뮬레이션으로 최적 조합과 뼈대가 다른 유력 대안을 찾는 것이 목표다.
**1차는 일반적인 허수아비 보스에서 조합·배치·큐브·컨트롤까지(1~3단계), 2차는 임의의 보스 대응(4단계)**이다.
알고리즘 개발에 시간을 투자하되, 계정별 탐색 효율은 **시뮬 횟수 대비 해 품질**로 평가한다. 응답 시간 상한은 미정이다.
캐릭터 추가 후 필요한 주기적 갱신의 시간·비용은 이 목표를 지속해서 수행할 기법의 운영 조건으로 함께 검토한다.
외부 평가기를 연결하는 Python CLI 프로젝트이며, 목표 기능과 현재 구현 상태는 아래 문서에서 구분한다.

## 문서 안내

| 필요한 내용 | 문서 |
|---|---|
| 목적·문제 정의·1·2차 목표와 네 단계·범위 | [GOALS.md](docs/GOALS.md) |
| 탐색 구조·평가 예산·성능 측정·선행 사례 | [SEARCH.md](docs/SEARCH.md) |
| 구현 현황·로드맵·기존 실험·다음 질문 | [ROADMAP.md](docs/ROADMAP.md) |
| 에이전트가 작업을 시작할 때 | [AGENTS.md](AGENTS.md) |
| 브랜치·검증·커밋·푸시 규칙 | [작업 규칙](rules/workflow.md) |
| 평가기·탐색·실험 작업의 준수 사항 | [평가 규칙](rules/evaluation.md) |
| 분석 기법 선택과 결과 보고 | [AI 분석 가이드](AI_분석가이드.md) |

## 평가기(계산기)

평가기는 교체 가능하다. 최적화 쪽은 「스쿼드 + 배치 순서 + 육성 + 큐브 + 컨트롤 + 보스 조건·패턴 → 180초 딜」
인터페이스만 안다.

| 평가기 | 상태 | 메모 |
|---|---|---|
| [Jgaram/nikke-calc](https://github.com/Jgaram/nikke-calc) (Python) | **연결됨 · 공개 기준** | 원본. 1회 약 4~8초(기대값 모드). 사전 실험 1–5는 이것으로 했다. Rust 실행 파일이 없으면 이것을 쓴다. 어댑터는 아래 「평가기 어댑터」 |
| [nikke-calculator-xi.vercel.app](https://nikke-calculator-xi.vercel.app/) | 보류 | moris 포크를 다른 사람이 이어받아 서비스 중. 계산은 브라우저 안에서 돈다(엔진 워커 JS 하나 + 공개 데이터 JSON) → 스냅샷을 떠서 Node에서 블랙박스로 돌릴 수는 있어 보인다(미검증). 소스·라이선스 미확인, 서비스 지속도 불확실 — 쓸지는 나중에 정한다 |
| moris-kr/nikke-calc (TypeScript/Node) | 사라짐 | 2026-10 레포 삭제(개인 사정). 원본에서 갈라진 TS 엔진(`site/src/engine/`), 기대값 모드 1회 약 0.9초였다 |
| Rust 포팅 `nikke-sim` (자체) | **연결됨 · 있으면 우선** | 별도 비공개 레포(`nikke-calc-rs`). 원본 `23164e4` 기준 포팅, 요청 v2를 그대로 받는다. S40 5인 기대값 1회 약 0.2초(원본 7.7초와 같은 총딜, 2026-10-29). 이 레포에는 코드·실행 파일을 두지 않고 실행 파일만 부른다. 디버그용 `DebugChar` 요청은 거절하고, 포팅의 정확도 기준은 「원본과 비슷하면 통과」다 |
| 딜도로 | 비공개 | Rust 포팅, 더 빠른 것으로 알려짐 |

외부 평가기 코드의 저장·공개 범위는 [작업 규칙](rules/workflow.md#저장소-경계)을 따른다.

원본과 포크는 이미 데이터·로직이 갈라지고 있다(같은 스쿼드도 결과가 조금 다르다). 결과에는
어느 평가기·어느 버전으로 냈는지 함께 남긴다.

### 평가기 어댑터 — `nikke_opt/evaluator.py`

평가기를 `--batch` 서브프로세스로만 부른다(계약: nikke-calc `docs/SIM-JSON.md`). 어댑터는 둘이고 `make_evaluator()`가 고른다.

| 어댑터 | 부르는 것 | 설정 |
|---|---|---|
| `NikkeSimEvaluator` (Rust) | `nikke-sim --batch` 프로세스 1개, 안에서 작업 스레드 `jobs`개(`NIKKE_BATCH_WORKERS`) | `NIKKE_SIM_BIN` = 실행 파일 경로 |
| `NikkeCalcEvaluator` (Python) | `python -m runner.sim --batch` 프로세스 `jobs`개(최대 8) | `NIKKE_CALC_DIR` = nikke-calc 체크아웃 |

기본(`auto`)은 `NIKKE_SIM_BIN`이 있으면 Rust, 없으면 Python이다. CLI는 `--evaluator rust|python`으로 강제한다.
**요청 JSON v2**(`schema_version: 2`, nikke-calc `167698c`부터)를 보내고, 판이 다른 결과는 받지 않는다 — 평가기가 계약을 바꾸면 바로 끊긴다.

```bash
NIKKE_SIM_BIN=../nikke-calc-rs/target/release/nikke-sim python -m nikke_opt.eval "리틀 머메이드,크라운,라피 : 레드 후드,미하라,헬름" --boss "솔로 레이드 S40"
NIKKE_CALC_DIR=../nikke-calc python -m nikke_opt.eval "리틀 머메이드,크라운,라피 : 레드 후드,미하라,헬름" --evaluator python
python -m unittest discover -s tests -t .      # 가짜 평가기로 돈다. NIKKE_SIM_BIN·NIKKE_CALC_DIR이 있으면 진짜로도 한 번
```

Rust 실행 파일은 `nikke-calc-rs`에서 `cargo build --release -p nikke-cli`로 만든다(`target/release/nikke-sim`, 게임 데이터 내장).

- **기대값 모드가 기본** — `sim.expected: true`, 1회로 결정론적이다. 평가는 언제나 180초(`sim.duration`은 거절).
- **요청 칸** — `EvalRequest(squad, boss, options)`의 `options`가 요청의 나머지 칸이다: `sim`(시드 등) · `enemy` · `operation`(카메라 · 택틱 · `auto`)
  · `profile`(육성, 아래) · `chars`(니케별 운용 — `control` dict · `cube` · `favorite_stage`). 2·3단계의 큐브·컨트롤을
  전달할 수 있는 기반이다. 입력 전달 지원과 해당 변수를 탐색·최적화하는 기능은 구분한다.
- **병렬** — Python은 `--batch` 프로세스 여러 개로, Rust는 프로세스 하나 안의 작업 스레드로 나눠 돈다. 응답 순서는 요청 순서 그대로다.
- **버전** — Python은 체크아웃의 `git rev-parse HEAD`·dirty, Rust는 시작할 때 짧은 요청 1회(시뮬 횟수에 안 셈)로 받은 결과의
  `evaluator` — 빌드 때의 `nikke-calc-rs` 커밋·dirty와 원본 기준 커밋(`port_of`). 실행 중에 이 값이 바뀌면 멈춘다.
- **캐시** — (평가기 커밋, 요청) → 결과. `.cache/evals.sqlite`(커밋 안 함). 키에 평가기 커밋이 들어가 Python·Rust 결과가 섞이지 않는다.
  평가기에 커밋 안 된 변경이 있으면(Rust는 dirty 빌드·커밋 모름) 캐시하지 않는다.
  패턴 파일 등 외부 참조의 내용이 바뀌는 경우까지 식별하는지는 4단계에서 검증·보완해야 한다.
- **보스 파일** — Rust는 `.json` 보스 경로를 지금 작업 폴더 기준 절대 경로로 바꿔 보낸다. Python은 nikke-calc 체크아웃 기준이다.
- **예산** — 실제로 돌린 시뮬 횟수만 센다(캐시 적중·같은 요청 중복은 안 셈). 넘칠 요청은 시작하지 않는다.
- **육성** — 요청에 인라인으로 싣는다. 평가기의 프로필 폴더(nikke-calc `profiles/`)에 파일을 쓰지 않는다(그 폴더는 개인 데이터다).
  형식의 정본은 nikke-calc `docs/SIM-JSON.md` §육성(nikke-calc `a4174a5`부터).
  Rust에서 프로필을 *이름*으로 주려면 프로필 폴더(`NIKKE_PROFILE_DIR` 또는 `profile_dir`)가 필요하다. 없으면 거절한다.

  ```python
  EvalRequest(squad, boss=BOSS, options={"profile": {
      "base": "default",   # 적지 않은 니케 = 기본 스펙 (생략하면 미육성)
      "chars": {"크라운": {"skill_levels": "7/7/7", "overload": {"우월 코드 대미지": 2, "공격력": 1}}},
  }})
  ```

  요청 줄이 곧 육성이라 캐시 키가 내용을 따라간다. 프로필을 *이름*으로 주면(내 계정 `me` 등) 파일 내용 해시를 키에 넣는다.

조사 결과 (2026-10-07, nikke-calc `ba9f29c`):

| 항목 | 결과 |
|---|---|
| 호출 | CLI `--json` · `--batch`(JSON Lines). 결과에 평가기 커밋이 실린다 |
| 육성 | 기본 스펙(레벨 400·오버로드 등)이 전원에게 같다 + 니케별 운용 레이어(`char_defaults.json`, `auto`로 끔). 계정 육성은 `profile` — 처음엔 nikke-calc `profiles/<이름>.json` 파일로만 받았다(실험 5는 이름에 내용 해시를 넣어 우회). **2026-10-08 nikke-calc `a4174a5`부터 인라인 dict**(`base: "default"`면 적지 않은 니케 = 기본 스펙, 스킬·오버로드 줄 수 표기)를 받는다 — 위 「육성」. 빈 항목 = 기본 스펙과 딜 일치 |
| 보스 | 파라미터화 가능 — 가상 보스를 만들 수 있다 |
| 계약 v2 | **2026-10-08 nikke-calc `167698c`**: 입력이 요청 JSON 한 가지로 — `sim.*` · `enemy.*` · `operation.*` · `profile` · `chars.<니케>.control/cube`. 정본은 JSON Schema(`python -m runner.request`), 오류는 칸을 JSON Pointer `path`로 가리킨다. v1 배치 키(`expected` 등)는 거절. 실험 2·5 표본 12개가 `ba9f29c` 기록과 소수 8자리까지 같은 딜 |
| 운용 | 니케별 컨트롤은 dict, 큐브는 니케마다 따로(`chars.<니케>.cube`, 모르는·효과 모델 없는 큐브는 오류). 결과에 조작 요약 `control_detail` |
| 배치 순서 | **딜을 바꾼다.** 같은 5명 역순이 기본 적 −9%, S40 −24%. 순서도 탐색 대상이다 |
| 병렬 | 프로세스 병렬 안전, 결과 동일 |
| 1회 비용 | 4~5초. 4코어면 2천 회 약 40분 |

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [Jgaram/nikke-calc](https://github.com/Jgaram/nikke-calc) | 1차 평가기. 게임 메커니즘 문서와 시뮬레이션 엔진 |
| [Jgaram/nikke-analysis](https://github.com/Jgaram/nikke-analysis) | 에닉 랭커 덱 수집·분석 (시즌 1–41, 6개 서버 상위 50명 × 5덱) |
