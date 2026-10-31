# 실험 15 — 진행 방식과 파일 소유

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 2026-10-31 사용자 지시: 경우 4~5개를 여러 세션에서 병렬로 알아보고 취합한다.
이 문서는 계획이다 — 아래 1단계(관리자 구현)부터 다음 세션에서 시작한다.

## 결정 — 관리자 1 + 작업 세션 5(경우별)

- 경우(C1~C5)는 서로 독립이고 각각 약 12만 시뮬 · 3~4시간이라, 한 컨테이너(4코어)로는 하루 가까이 걸린다. 세션 하나에 경우 하나를 맡겨 병렬로 돌린다.
- 판단에 쓰는 비교(O · I1 · I2 대 F4)는 모두 같은 경우 안에서 끝나므로 세션마다 시뮬을 따로 세도 된다. 시뮬 횟수는 세션별로 기록한다(캐시가 컨테이너마다 따로).
  계정 결과(5덱 합)는 결정론이라 캐시 유무와 상관없이 같다 — F4(실험 13 U4) 기록을 다른 컨테이너의 결과와 그대로 비교한다.
- 작업 세션은 다른 세션을 열지 않는다. 관리자만 `create_session`으로 연다.

## 단계

1. **관리자 — 공용 코드 · 테스트 · 사전 등록 확인 커밋(작업 세션을 열기 전에).**
   - `run15.py`: `precompute --case C<k> --seed <k>`(구 풀 PB15, 계정 id `pre-<경우>-s<k>`), `merge --case`(O · I1 · 근사), `update --case`(I2),
     `search --case --methods O,I1,I2[,F4] [--missing-new]`(계정 L0는 177명, `--missing-new`면 시나리오 id `v<k>n`에 새 니케 미보유), `collect`.
   - `analyze15.py`: `--case C<k>`면 그 경우의 표 · 판단(README §판단 기준), 인수 없이 `cases/*/`를 모아 취합 표 · 기본 갱신 절차.
   - `tests/test_exp15_*.py`: 경우 목록 고정(README 표와 같은지), 구 풀에 새 니케가 없음, I2 단계 예산, 미보유 시나리오, 판단 규칙(합성 자료).
   - 경우 목록은 README 표를 그대로 코드 상수로 둔다(다시 고르지 않는다).
2. **작업 세션 C1~C5 — 동시에.** 각자 `bash tools/setup_evaluators.sh` 뒤:
   구 풀 사전 계산 4개(프로세스 4개 동시) → `merge` → `update` → 계정 보유 48실행(프로세스 4개, 시나리오 2개씩) → 미보유 32실행 → `collect` → `analyze15.py --case`.
   상한 15만 시뮬(README §예산과 실행의 순서로 뺀다). 끝나면 관리자에게 `send_message`로 보고(아래).
3. **관리자 — 취합.** 모든 경우의 `cases/C<k>/`를 받아 `analyze15.py`로 취합 · README 결과 · 해석 · 로드맵 · 다음 회차 초안.

## 파일 소유

| 파일 | 소유 |
|---|---|
| `README.md` · `SESSIONS.md` · `run15.py` · `analyze15.py` · `tests/test_exp15_*.py` · `results.md`(취합) | 관리자 |
| `cases/C<k>/**`(`run_log/` · `results.md` · `notes.md`) | 그 경우의 작업 세션 |
| `docs/` · 레포 `README.md` · `rules/` · `AGENTS.md` | 관리자 |

작업 세션이 공용 코드를 고쳐야 하면(버그 등) 직접 고치지 않고 관리자에게 알린다. 관리자가 고치고 다른 세션에도 알린다.

## 인터페이스

- `cases/C<k>/run_log/`:
  - `precompute_O-s<k>.json` · `.jsonl.gz`(구 풀 시드별, 실험 12 형식에 `case` · `removed`), `precompute_O.json` · `precompute_I1.json`(실험 13 합친 판 형식),
    `precompute_I2.json` · `.jsonl.gz`(I2 탐색 기록, `stages`에 설계 · 넣기 · 국소 탐색 평가 수), `approx.json`(걸러 낸 근사, 관찰).
  - `val_summary.jsonl` · `val_evals.jsonl.gz`(실험 10 형식, 실행 이름 `<sid>_P177_<기호>_<예산>`, 미보유는 `<sid>` = `v<k>n`), `meta.json`(세션별 실제 시뮬 · 시간 · 평가기 · 뺀 것).
- F4 보유 조건 = 실험 13 `run_log/val_summary.jsonl`의 `U4`(분석에서 기호를 F4로 읽는다). F4 미보유 조건은 경우마다 새로 돈다.
- **보고(작업 세션 → 관리자, `send_message`):** 커밋 해시 · 테스트 결과 · 실제 시뮬 횟수(사전 계산 · 계정) · 경우 판단 줄 · 표의 핵심 수치 · 뺀 실행 · 막힌 점.
  막히면(평가기 · 접근 · 시간) 우회하거나 가짜 결과로 채우지 않고 바로 알린다.
- 작업 세션의 커밋은 `cases/C<k>/`만 담는다. push 전에 `git fetch origin main && git merge origin/main`, 테스트(`python -m unittest discover -s tests -t .`).

## 작업 세션 첫 메시지(관리자가 보낼 내용의 틀)

> 실험 15 경우 C<k>(새 니케: …)를 맡는다. `experiments/15_new_nikke/README.md` · `SESSIONS.md`를 읽고 2단계를 그대로 실행하라. 소유는 `cases/C<k>/`뿐이다.
> 판단 기준은 README 그대로이며 바꾸지 않는다. 끝나면 SESSIONS.md 「보고」 항목으로 관리자 세션 `<id>`에 send_message.
