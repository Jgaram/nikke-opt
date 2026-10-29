"""실험 6 해석용 진단 — 참조 탐색 최선에서 선택지를 하나씩 빼 본다. (관리자)

본 실행 뒤 넷째 줄(참조 > 좌표 하강)의 원인을 보려고 만들었다. 조합마다:
1. 참조 최선 S에서 선택지 v 하나를 뺀 S − v를 평가한다. 뺐을 때 딜이 `--drop`(기본 0.1%) 이상 줄면 v는 **필수**.
2. 필수 선택지만 모은 E를 평가한다(S의 이득을 E가 거의 다 설명하는지).
3. E의 선택지 하나씩만 기본 레이어에 얹어 평가한다(혼자서는 이득이 없는데 함께면 있는지 — 상호작용).

    source .cache/evaluators.env && python experiments/06_control_menu/ablate.py \
        experiments/06_control_menu/run_log/main.jsonl --comps c04,c17,c24,c29 --out run_log/ablation.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
import common  # noqa: E402
import menu  # noqa: E402
from nikke_opt.evaluator import EvalRequest, make_evaluator  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("records", type=Path)
    ap.add_argument("--comps", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--drop", type=float, default=0.001)
    args = ap.parse_args(argv)

    comps = {c["id"]: c for c in common.load_compositions()}
    recs = list(common.read_records([args.records]))
    ev = make_evaluator("rust")
    out = []
    with ev:
        for cid in args.comps.split(","):
            squad = comps[cid]["squad"]
            vmap = {v["label"]: v for vs in menu.variants(squad).values() for v in vs}

            def best(cond: str) -> dict:
                rs = [r for r in recs if r["comp_id"] == cid and r["condition"] == cond and r["total_damage"]]
                return max(rs, key=lambda r: (r["total_damage"], -len(r["variants"])))

            ref, sfl, layer = best("reference"), best("search_from_layer"), best("layer")
            S = list(ref["variants"])

            def damage(labels: list[str]) -> int | None:
                opts = menu.apply({}, [vmap[x] for x in labels]) if labels else {}
                return ev.evaluate([EvalRequest(tuple(squad), options=opts)])[0].total_damage

            drops = {v: damage([x for x in S if x != v]) for v in S}
            essential = [v for v in S if drops[v] is not None and drops[v] < ref["total_damage"] * (1 - args.drop)]
            e_dmg = damage(essential)
            singles = {v: damage([v]) for v in essential}
            row = {"comp_id": cid, "layer": layer["total_damage"], "search_from_layer": sfl["total_damage"],
                   "reference": ref["total_damage"], "reference_variants": S,
                   "drop": {v: (d / ref["total_damage"] - 1 if d else None) for v, d in drops.items()},
                   "essential": essential, "essential_damage": e_dmg,
                   "essential_vs_layer": e_dmg / layer["total_damage"] - 1 if e_dmg else None,
                   "single_vs_layer": {v: (d / layer["total_damage"] - 1 if d else None) for v, d in singles.items()}}
            out.append(row)
            print(json.dumps({k: row[k] for k in ("comp_id", "essential", "essential_vs_layer", "single_vs_layer")},
                             ensure_ascii=False))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    print(f"시뮬 {ev.sim_count}회 · 캐시 적중 {ev.cache_hits}회", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
