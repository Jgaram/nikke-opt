"""실험 7 상한 참조 — 실험 6 `search.py`의 `reference`(무작위 출발 10 + 킥 5, 시드 0)를 조합마다 스레드로 돌린다.

    source .cache/evaluators.env && python experiments/07_control_search/ref_run.py --out <dir> [--comps v01,v02]

조합마다 `<dir>/ref_<comp>.jsonl`(실험 6 Record 형식)과 끝나면 `.done`(요약). 이미 끝난 조합은 건너뛴다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
sys.path[:0] = [str(EXP6), str(HERE.parent.parent)]
import common  # noqa: E402
import search  # noqa: E402

STARTS, KICKS, SEED = 10, 5, 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compositions", type=Path, default=HERE / "val_compositions.json")
    ap.add_argument("--comps", default="all")
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args(argv)
    comps = common.load_compositions(args.compositions)
    if args.comps != "all":
        comps = [c for c in comps if c["id"] in args.comps.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    todo = [c for c in comps if not (args.out / f"ref_{c['id']}.done").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()

    def work(c):
        out = args.out / f"ref_{c['id']}.jsonl"
        s = search.run_condition(c, "reference", ev, out=out, seed=SEED, reference_starts=STARTS, reference_kicks=KICKS)
        s = {k: v for k, v in s.items() if k != "starts"}
        (args.out / f"ref_{c['id']}.done").write_text(json.dumps(s, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({**s, "t": round(time.time() - t0), "sims_total": ev.sim_count}, ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            for f in [pool.submit(work, c) for c in todo]:
                f.result()
    print(f"조합 {len(todo)}개 · 시뮬 {ev.sim_count}회 · {time.time() - t0:.0f}초", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
