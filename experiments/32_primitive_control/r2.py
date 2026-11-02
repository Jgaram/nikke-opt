"""실험 32 R2 — 무엇이 덱 순위를 바꾸는 큰 축인가(README §R2 사전 등록).

    python -I experiments/32_primitive_control/r2.py plan          # 덱 고르기 → r2/decks.json (시뮬 0)
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r2.py run   # 기준 덱 A + 표본 덱의 한 선택지씩
    python -I experiments/32_primitive_control/r2.py analyze       # → r2.json · r2.md

바탕은 레이어 끔(`operation.auto: true`, R1의 P와 같다). 메뉴는 R1 `prim_variants`(원시 입력).
축 = 원시 입력 묶음: burst_who(단계마다 누가) · burst_t(딜레이 · 쿨 대기) · click · cover(cover_at · cover_fb · cancel) · camera.
덱마다 「그 축의 선택지 하나만 바꾼」 변형을 모두 재고, 축 이득 = max(1, 그 축 변형 최고 ÷ 바탕).
"""

from __future__ import annotations

import json
import random
import statistics as st
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import r1  # noqa: E402
from r1 import run31, r0  # noqa: E402

OUT = HERE / "r2"
SEED = 32
REF_TOP = 200                       # 시즌 기준 덱: 옛 기록 상위 200(바탕만 잰다) → 상위 100 문턱 T · 150위 값
STRATA = ((0, 100, 10), (100, 1000, 10), (1000, 10000, 6))   # (옛 기록 순위 시작, 끝, 표본 수)
N_RANK = 4                          # 랭커 대표 5덱 · 1위 5덱 중 무작위
AXES = {"burst_who": "burst_who", "burst_t": "burst_t", "click": "click", "cover_at": "cover", "cover_fb": "cover",
        "cancel": "cover", "camera": "camera"}
X_MIN = 0.05                        # 큰 축: 상위 100 밖 표본 중 그 축만으로 상위 100에 드는 비율 ≥ 5%(임시)


def axis_of(v: Mapping[str, Any]) -> str:
    a = v["axis"]
    return AXES["burst_who" if a.startswith("burst_who") else a]


def cmd_plan() -> int:
    rng = random.Random(SEED)
    out = {"ref": {}, "sample": []}
    for s in run31.SEASONS:
        bk = run31.book(s, "nocore", "B")
        order = sorted(bk.values(), key=lambda x: -x[0])
        out["ref"][str(s)] = [list(q) for _, q in order[:REF_TOP]]
        picked: set[frozenset] = set()
        for a, b, n in STRATA:
            pool = [q for _, q in order[a:b] if frozenset(q) not in picked]
            for q in rng.sample(pool, min(n, len(pool))):
                picked.add(frozenset(q))
                out["sample"].append({"season": s, "squad": list(q), "stratum": f"{a}-{b}", "old_rank": next(
                    i for i, (_, x) in enumerate(order) if x == q)})
        rk = run31.ranker_decks(s)
        rq = [q for q in rk["top_five"] + rk["rank1"] if all(n[0] not in "?!" for n in q) and frozenset(q) not in picked
              and all(n in r1.nikke_info() for n in q)]
        rq = list(dict.fromkeys(tuple(q) for q in rq))
        for q in rng.sample(rq, min(N_RANK, len(rq))):
            picked.add(frozenset(q))
            out["sample"].append({"season": s, "squad": list(q), "stratum": "ranker", "old_rank": None})
    for i, d in enumerate(out["sample"]):
        d["id"] = f"r2-{i:03d}"
    OUT.mkdir(exist_ok=True)
    (OUT / "decks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    nv = 0
    for d in out["sample"]:
        sp = r1.space(d, "P")
        nv += sp.nv
    print("표본", len(out["sample"]), "변형", nv, "기준", sum(len(v) for v in out["ref"].values()))
    return 0


def cmd_run() -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    D = json.loads((OUT / "decks.json").read_text(encoding="utf-8"))
    t0 = time.time()
    with make_evaluator("rust", jobs=4, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        f = OUT / "ref.json"
        if not f.exists():
            ref = {}
            for s, qs in D["ref"].items():
                res = ev.evaluate([EvalRequest(q, boss=None, options=r0.opts(int(s), False)) for q in qs])
                ref[s] = {",".join(q): None if r.total_damage is None else r.total_damage / 1e8 for q, r in zip(qs, res)}
                print(json.dumps({"ref": s, "sims": ev.sim_count, "t": round(time.time() - t0)}), flush=True)
            f.write_text(json.dumps(ref, ensure_ascii=False) + "\n", encoding="utf-8")
        g = OUT / "sample.jsonl"
        done = {json.loads(x)["id"] for x in g.read_text(encoding="utf-8").splitlines()} if g.exists() else set()
        with g.open("a", encoding="utf-8") as fh:
            for d in D["sample"]:
                if d["id"] in done:
                    continue
                sp = r1.space(d, "P")
                sels = [sp.empty()]
                for i in range(sp.nv):
                    s = list(sp.empty())
                    s[sp.key_of[i]] = i
                    sels.append(tuple(s))
                reqs = [EvalRequest(d["squad"], boss=None, options=sp.options(x)) for x in sels]
                res = ev.evaluate(reqs)
                rec = {"id": d["id"], "base": res[0].total_damage / 1e8,
                       "vars": [[sp.vars[i]["label"], axis_of(sp.vars[i]), None if r.total_damage is None else r.total_damage / 1e8]
                                for i, r in zip(range(sp.nv), res[1:])], "errors": sum(1 for r in res if r.error)}
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(json.dumps({"id": d["id"], "n": len(sels), "sims": ev.sim_count, "t": round(time.time() - t0)}), flush=True)
        (OUT / "run_meta.json").write_text(json.dumps({"sims": ev.sim_count, "seconds": round(time.time() - t0, 1), "evaluator": ver},
                                                      ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def cmd_analyze() -> int:
    D = json.loads((OUT / "decks.json").read_text(encoding="utf-8"))
    ref = json.loads((OUT / "ref.json").read_text(encoding="utf-8"))
    recs = {json.loads(x)["id"]: json.loads(x) for x in (OUT / "sample.jsonl").read_text(encoding="utf-8").splitlines()}
    # 시즌 문턱: 기준 덱(옛 상위 200) ∪ 표본의 바탕 값으로 100위 · 150위
    thr, gap = {}, []
    for s in run31.SEASONS:
        vals = [v for v in ref[str(s)].values() if v] + [recs[d["id"]]["base"] for d in D["sample"] if d["season"] == s]
        vals.sort(reverse=True)
        thr[s] = vals[99]
        gap.append(vals[99] / vals[149] - 1)
    y_min = st.median(gap)          # 큰 축: 이득 중앙 ≥ (100위 ÷ 150위 − 1)의 시즌 중앙(사전 등록한 공식)
    axes = sorted({a for a in set(AXES.values())})
    per = {a: {"gain": [], "cross": 0, "outside": 0, "has": 0} for a in axes}
    rows = []
    for d in D["sample"]:
        r = recs[d["id"]]
        b = r["base"]
        g = {}
        for a in axes:
            vs = [v for _, ax, v in r["vars"] if ax == a and v]
            if vs:
                g[a] = max(1.0, max(vs) / b)
        outside = b < thr[d["season"]]
        for a in axes:
            if a not in g:
                continue
            per[a]["has"] += 1
            per[a]["gain"].append(g[a])
            if outside:
                per[a]["outside"] += 1
                per[a]["cross"] += b * g[a] >= thr[d["season"]]
        top = sorted(r["vars"], key=lambda x: -(x[2] or 0))[:3]
        rows.append({**d, "base": b, "thr": thr[d["season"]], "gain": g, "top3": top})
    summ = {"y_min": y_min, "x_min": X_MIN, "thr": thr, "axes": {}}
    for a in axes:
        p = per[a]
        cross = p["cross"] / p["outside"] if p["outside"] else 0.0
        gm = st.median(p["gain"]) - 1 if p["gain"] else 0.0
        summ["axes"][a] = {"decks": p["has"], "gain_median": gm, "gain_p90": sorted(p["gain"])[int(0.9 * (len(p["gain"]) - 1))] - 1 if p["gain"] else 0,
                           "gain_max": max(p["gain"]) - 1 if p["gain"] else 0, "outside": p["outside"], "cross": p["cross"], "cross_share": cross,
                           "big": cross >= X_MIN or gm >= y_min}
    meta = OUT / "run_meta.json"
    if meta.exists():
        summ["run"] = json.loads(meta.read_text(encoding="utf-8"))
    (HERE / "r2.json").write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    md = [f"y(이득 중앙 문턱) = {y_min:.2%}, x(상위 100 진입 비율 문턱) = {X_MIN:.0%}", "",
          "| 축 | 덱 | 이득 중앙 | 90백분위 | 최대 | 상위 100 밖 → 진입 | 큰 축 |", "|---|---|---|---|---|---|---|"]
    for a, v in sorted(summ["axes"].items(), key=lambda kv: -kv[1]["gain_median"]):
        md.append(f"| {a} | {v['decks']} | {v['gain_median']:.2%} | {v['gain_p90']:.2%} | {v['gain_max']:.1%} | "
                  f"{v['cross']}/{v['outside']} ({v['cross_share']:.1%}) | {'**예**' if v['big'] else '아니오'} |")
    (HERE / "r2.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"plan": cmd_plan, "run": cmd_run, "analyze": cmd_analyze}.get(cmd, lambda: (print(__doc__), 2)[1])())
