"""스쿼드 평가 CLI — 평가기 어댑터를 손으로 부를 때 쓴다.

    NIKKE_CALC_DIR=../nikke-calc python -m nikke_opt.eval "리틀 머메이드,크라운,라피 : 레드 후드,미하라,헬름"
    python -m nikke_opt.eval "A,B,C,D,E" "E,D,C,B,A" --boss "솔로 레이드 S40" --jobs 4
    python -m nikke_opt.eval "A,B,C,D,E" --boss '{"def": 50000, "code": "철갑"}'

stdout: 스쿼드마다 결과 JSON 한 줄. stderr: 시뮬 횟수·캐시 적중 요약.
"""

from __future__ import annotations

import argparse
import json
import sys

from nikke_opt.evaluator import EvalRequest, NikkeCalcEvaluator


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="스쿼드를 180초 시뮬로 평가한다")
    ap.add_argument("squads", nargs="+", help="콤마로 구분한 스쿼드 (배치 순서 그대로)")
    ap.add_argument("--boss", help="프리셋 이름, .json 경로, 또는 인라인 JSON 객체")
    ap.add_argument("--calc-dir", help="nikke-calc 체크아웃 (기본: NIKKE_CALC_DIR)")
    ap.add_argument("--jobs", type=int, help="병렬 프로세스 수 (기본: CPU 수, 최대 8)")
    ap.add_argument("--budget", type=int, help="시뮬 횟수 상한")
    ap.add_argument("--no-cache", action="store_true", help="결과 캐시를 쓰지 않는다")
    args = ap.parse_args(argv)

    boss = json.loads(args.boss) if args.boss and args.boss.lstrip().startswith("{") else args.boss
    ev = NikkeCalcEvaluator(args.calc_dir, jobs=args.jobs, budget=args.budget,
                            cache=not args.no_cache)
    requests = [EvalRequest(tuple(n.strip() for n in s.split(",")), boss=boss) for s in args.squads]
    failed = False
    for req, res in zip(requests, ev.evaluate(requests)):
        failed |= res.error is not None
        print(json.dumps({"squad": list(req.squad), "total_damage": res.total_damage,
                          "cached": res.cached, "error": res.error, "evaluator": ev.version},
                         ensure_ascii=False))
    print(f"시뮬 {ev.sim_count}회 · 캐시 적중 {ev.cache_hits}회 · 평가기 {ev.version['commit'][:7]}"
          f"{' (dirty — 캐시 안 함)' if ev.version['dirty'] else ''}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
