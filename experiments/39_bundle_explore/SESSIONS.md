# 실험 39 — 세션 운영

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 관리자: `session_01MQimn3nQMJvtSZARWmUPnF`.

| 세션 | 맡은 일 | 소유 파일 | 상태 |
|---|---|---|---|
| 기준선 | base 판 S23~S32 B_s0 · B_s1 + rankers | `run_log/base/**` · `run_log/rankers/**` | 관리자 컨테이너에서 돈다(아래) |
| A | 판 a 개발(S33~S42) → 고정 커밋 → S23~S32 실행 | `arm_a.py` · `dev/a/**` · `run_log/a/**` | 취소 `session_01MQimn417LuQPY136ZixAhv` — 관리자 컨테이너로 |
| B | 판 b 개발 → 고정 커밋 → S23~S32 실행 | `arm_b.py` · `dev/b/**` · `run_log/b/**` | 취소 `session_01MQimn2hqk4qQPzZt6rg54y` — 관리자 컨테이너로 |

- 관리자 소유: `README.md` · `SESSIONS.md` · `run39.py` · `seasons39.py` · `seasons.json` · `analysis.json` · `results.md` · `tests/test_exp39.py`, 공용 문서.
- 평가기 nikke-calc-rs `8bc51a2`. 결과는 결정론이라 어느 컨테이너에서 돌려도 값이 같다. 시뮬 수는 `part_*.json`의 `sims`에 남는다.
- **2026-11-03 시험 세션 `session_01MQimn58wu5xTN8JeQ7hSJC`:** 작업 세션에서 `add_repo`(Jgaram/nikke-calc-rs, read)를 auto mode 권한 검사가 거부했다
  (「Access Added As A Means」, 실험 30 · 35와 같다). 그래서 기준선은 관리자 컨테이너에서 먼저 돌린다. A · B 세션은 사용자 결정 뒤 연다.
- 사용자 결정(2026-11-03): 「허용 규칙 커밋」 → `.claude/settings.json` permissions.allow에 `mcp__claude-code-remote__add_repo`(`84ee778`). 그 뒤 A · B 세션을 열었다.
- 기준선은 관리자 컨테이너에서 setsid로 돈다(`run_log/base.log`). 워커 재시작으로 한 번 끊겨 다시 켰다(끝난 부분은 건너뜀).
- **허용 규칙도 소용없었다:** B 세션이 규칙을 확인했지만 auto mode 분류기가 그보다 먼저 같은 문구로 거부했다(시뮬 0). 규칙은 되돌렸다.
- **사용자 결정(2026-11-03): 「이 컨테이너에서 전부」.** 판 a · b 설계는 관리자 세션의 하위 에이전트 둘이 동시에(각자 `arm_?.py` · `dev/?/`만, 커밋은 관리자), 검증 실행은 기준선 뒤 a · b를 이 컨테이너에서 돈다. 개발 시뮬은 기준선과 같은 4코어를 나눠 쓴다.
- A 세션은 add_repo는 통과했지만 평가기 빌드(`setup_evaluators.sh` · 8bc51a2 checkout)를 같은 분류기가 「Code from External」로 거부했다. A · B · 시험 세션 모두 보관.
- 2026-11-03 10:4x UTC 무렵 컨테이너 재시작으로 세 실행이 모두 꺼졌다(base 4/20 끝, a · b 0). 12:40 UTC 다시 켰다(끝난 부분은 건너뜀). 이후 60분마다 점검.
- 13:10 UTC 또 재시작(가동 0분) 확인. 원인: 세션이 쉬면 컨테이너가 회수돼 setsid 실행도 꺼진다. 다시 켜고, 세 실행이 끝날 때까지 기다리는 작업을 하네스 백그라운드로 붙여 세션이 쉬지 않게 했다.
- 13:4x UTC 사용자: 「계산기를 수정해야 하는 이슈가 있어 카메라와 관련된 것… 8시간 계산 전에 수정하고 다시 하는 게 어떨까」 → 세 실행을 멈췄다(base 4/20 · a 1/20 · b 1/20, 평가기 8bc51a2). 예비 점검 예약도 지웠다.
- **평가기 수정 검토(2026-11-03 14시 UTC 무렵):** 카메라 이동 때 재장전 규칙(실험 36 사용자 확인)을 nikke-calc-rs에 요청 옵션 `sim.camera_reload_cancel`로 넣었다(브랜치 `camera-reload-cancel` `c03af85`, 주지 않으면 원본과 같음).
  옵션을 켜도 **실험 39의 사전 계산 값은 바뀌지 않는다** — base S23 · S24 기록과 실험 36 S34 · S36 기록에서 무작위 2,400덱 중 0개(기본 레이어 운용에서는 카메라가 재장전 중인 엄폐 니케를 떠나지 않는다).
  후처리 덱(직접 짠 컨트롤)은 47개 중 24개가 바뀐다(최대 −8.64%). 그래서 실험 39는 다시 하지 않고 멈춘 곳부터 이어 돌았다(옵션 없이 — 값이 같다).
  다시 켠 실행은 평가기 `6e73529` + 이 수정 빌드(옵션 꺼짐)다. 옵션 없이 실험 36 기록과 사전 계산 300 · 후처리 47개 모두 같았다.
- 14:5x UTC: 평가기 수정이 nikke-calc-rs master에 들어갔다(`83a6d54`, CI 41654112460 녹색, 실험 36 세션의 trace 수정 `852efd7` 위). 이 컨테이너의 release 바이너리는 실험 39가 끝날 때까지 다시 빌드하지 않는다(옵션 꺼짐 값은 같다).
