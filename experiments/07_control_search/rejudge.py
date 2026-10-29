"""실험 7 — 채택 기법의 기록으로 실험 6 판단 기준 표(1~4줄)를 다시 적용한다 (README §판단 기준).

실험 6 기록에서 `search_from_layer` · `search_from_auto`를 빼고, 채택 기법의 개발 32개 실행 기록(첫 `budget`평가)을
`search_from_layer`(출발점 `layer`) 자리에 넣어 실험 6 `analyze.py`를 그대로 돌린다. 수치 기준은 실험 6 기본값이다.

    python experiments/07_control_search/rejudge.py --runs <dir>... --method M3:k2 --budget 400 --out <md> [--json <json>]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP6 = HERE.parent / "06_control_menu"
sys.path[:0] = [str(EXP6), str(HERE.parent.parent)]
import analyze  # noqa: E402  (실험 6)
import common  # noqa: E402


def records(run_dirs: list[Path], method: str, budget: int) -> list[dict]:
    out = []
    with gzip.open(EXP6 / "run_log" / "main.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["condition"] not in ("search_from_layer", "search_from_auto"):
                out.append(r)
    stem = method.replace(":", "_")
    for d in run_dirs:
        for p in sorted(d.glob(f"*__{stem}.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r["method"] != method or r["step"] >= budget:
                    continue
                out.append({"comp_id": r["comp_id"], "condition": "search_from_layer", "start": "layer",
                            "step": r["step"], "variants": r["variants"], "request": None,
                            "total_damage": r["total_damage"], "control_detail": None,
                            "cached": r["cached"] is not False, "error": r["error"], "evaluator": None,
                            "sim_count": r["sim_count"]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=Path, nargs="+", required=True)
    ap.add_argument("--method", required=True)
    ap.add_argument("--budget", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    recs = records(a.runs, a.method, a.budget)
    comps = common.load_compositions(EXP6 / "compositions.json")
    got = {r["comp_id"] for r in recs if r["condition"] == "search_from_layer"}
    missing = sorted({c["id"] for c in comps} - got)
    if missing:
        print(f"채택 기법 기록이 없는 조합: {missing}", file=sys.stderr)
        return 1
    s = analyze.summarize(recs, comps)
    head = (f"# 실험 7 — 채택 기법 {a.method}({a.budget}평가)로 다시 적용한 실험 6 판단 표\n\n"
            f"`rejudge.py`가 만든다. 실험 6 `analyze.py`의 `search_from_layer` 자리에 {a.method}의 첫 {a.budget}평가 기록을 넣었다"
            f"(카메라 빼앗김 집계는 이 기록에 `control_detail`이 없어 비어 있다).\n\n")
    a.out.write_text(head + analyze.render(s).split("\n", 1)[1], encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"criteria": s["criteria"], "candidate": s["candidate"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
