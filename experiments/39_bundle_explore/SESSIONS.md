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
