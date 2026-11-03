# 실험 39 — 세션 운영

[작업 규칙 §여러 세션](../../rules/workflow.md#여러-세션으로-진행할-때)을 따른다. 관리자: `session_01MQimn3nQMJvtSZARWmUPnF`.

| 세션 | 맡은 일 | 소유 파일 | 상태 |
|---|---|---|---|
| 기준선 | base 판 S23~S32 B_s0 · B_s1 + rankers | `run_log/base/**` · `run_log/rankers/**` | 관리자 컨테이너에서 돈다(아래) |
| A | 판 a 개발(S33~S42) → 고정 커밋 → S23~S32 실행 | `arm_a.py` · `dev/a/**` · `run_log/a/**` | `session_01MQimn417LuQPY136ZixAhv`(2026-11-03 08:35 UTC) |
| B | 판 b 개발 → 고정 커밋 → S23~S32 실행 | `arm_b.py` · `dev/b/**` · `run_log/b/**` | `session_01MQimn2hqk4qQPzZt6rg54y`(2026-11-03 08:35 UTC) |

- 관리자 소유: `README.md` · `SESSIONS.md` · `run39.py` · `seasons39.py` · `seasons.json` · `analysis.json` · `results.md` · `tests/test_exp39.py`, 공용 문서.
- 평가기 nikke-calc-rs `8bc51a2`. 결과는 결정론이라 어느 컨테이너에서 돌려도 값이 같다. 시뮬 수는 `part_*.json`의 `sims`에 남는다.
- **2026-11-03 시험 세션 `session_01MQimn58wu5xTN8JeQ7hSJC`:** 작업 세션에서 `add_repo`(Jgaram/nikke-calc-rs, read)를 auto mode 권한 검사가 거부했다
  (「Access Added As A Means」, 실험 30 · 35와 같다). 그래서 기준선은 관리자 컨테이너에서 먼저 돌린다. A · B 세션은 사용자 결정 뒤 연다.
- 사용자 결정(2026-11-03): 「허용 규칙 커밋」 → `.claude/settings.json` permissions.allow에 `mcp__claude-code-remote__add_repo`(`84ee778`). 그 뒤 A · B 세션을 열었다.
- 기준선은 관리자 컨테이너에서 setsid로 돈다(`run_log/base.log`). 워커 재시작으로 한 번 끊겨 다시 켰다(끝난 부분은 건너뜀).
