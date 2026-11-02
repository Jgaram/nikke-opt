"""실험 32 R0 — 고친 계산기로 기준선 다시 재기(관찰, 판정 없음). README §R0 사전 등록.

    source .cache/evaluators.env && python -I experiments/32_primitive_control/r0.py run       # 시뮬 약 1,412
    python -I experiments/32_primitive_control/r0.py analyze [nikke-analysis 경로]             # 시뮬 0 → r0.json · r0.md

덱: 시즌마다 랭커 덱(대표 5 · 1위 5 · 상위 40, 실험 31 `ranker_decks`) ∪ 실험 31 지도 대표 덱(`nocore|B`, 95% 아래 제외).
판: L = 레이어 켬(실험 31 `options`, 지금 절차), A = 레이어 끔(같은 options + `operation.auto: true`). 코어 없음 · 180초 · 기대값.
옛 값: 진단 `diag/rotate10.json.gz`(nikke-calc-rs 5bb2cb0, 기본 규칙 · 새 규칙 흉내)와 실험 31 기록(지도 대표 덱).
"""

from __future__ import annotations

import copy
import gzip
import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXP31 = ROOT / "experiments" / "31_recent_seasons"
sys.path[:0] = [str(ROOT), str(EXP31)]
import run31  # noqa: E402

OUT = HERE / "r0"
E8 = 1e8
LOW = 1.4          # 「실전 대비 크게 낮은 덱」: (실전/계산) ÷ 시즌 중앙 ≥ 1.4 (사전 등록)
LAYER_GAP = 0.05   # 레이어 의존: |L/A − 1| ≥ 5%를 따로 센다(사전 등록)
MIN_USERS = 10     # 실전 딜: 랭커 10명 이상이 쓴 덱(진단과 같다)


def decks_of(s: int) -> dict[str, list[tuple]]:
    rk = run31.ranker_decks(s)
    ok = lambda q: all(n[0] not in "?!" for n in q)  # noqa: E731
    m = run31.class_map(s, "nocore", "B")
    g = {k: [tuple(q) for q in v if ok(q)] for k, v in rk.items()}
    g["reps"] = run31.rep_decks(m)
    g["A"] = [tuple(q) for q in m["reps"][0]["decks"]]
    return g


def opts(s: int, layer: bool) -> dict:
    o = copy.deepcopy(run31.options(s, 0))
    if not layer:
        o.setdefault("operation", {})["auto"] = True
    return o


def cmd_run() -> int:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    OUT.mkdir(exist_ok=True)
    with make_evaluator("rust", jobs=4, cache=False) as ev:
        ver = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for s in run31.SEASONS:
            f = OUT / f"S{s}.json"
            if f.exists():
                continue
            t0, n0 = time.time(), ev.sim_count
            g = decks_of(s)
            todo = sorted({q for v in g.values() for q in v})
            reqs = [EvalRequest(list(q), boss=None, options=opts(s, lay)) for lay in (True, False) for q in todo]
            res = ev.evaluate(reqs)
            k = len(todo)
            vals = {}
            for i, q in enumerate(todo):
                rl, ra = res[i], res[k + i]
                vals[",".join(q)] = {"L": None if rl.total_damage is None else rl.total_damage / E8,
                                     "A": None if ra.total_damage is None else ra.total_damage / E8,
                                     "L_members": [[x["name"], round(x["damage"] / E8, 3)] for x in rl.raw.get("members", [])]}
            out = {"season": s, "evaluator": ver, "groups": {k2: [list(q) for q in v] for k2, v in g.items()}, "vals": vals,
                   "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1)}
            f.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"season": s, "decks": k, "sims": out["sims"], "s": out["seconds"], "ev": ver}, ensure_ascii=False), flush=True)
    return 0


def rank(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        for t in range(i, j + 1):
            r[o[t]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def real_damage(an: Path) -> dict[int, dict[frozenset, list[float]]]:
    import seasons31
    D = seasons31.Data31(an)
    out = {}
    for s in run31.SEASONS:
        end = D.seasons[s]["end_at"]
        real = defaultdict(list)
        for p in D.ranks(s):
            for t in p["teams"]:
                names = [D.to_eval(en, end) for en in t["characters"]]
                if any(n[0] in "?!" for n in names):
                    continue
                real[frozenset(names)].append(t["damage"] / E8)
        out[s] = real
    return out


def cmd_analyze(an: Path) -> int:
    old = json.loads(gzip.open(HERE / "diag" / "rotate10.json.gz").read())
    real = real_damage(an)
    rows, md = [], []
    for s in run31.SEASONS:
        d = json.loads((OUT / f"S{s}.json").read_text(encoding="utf-8"))
        V, g = d["vals"], d["groups"]
        ov = old[str(s)]["vals"]
        bk = run31.book(s, "nocore", "B")
        key = lambda q: ",".join(q)  # noqa: E731
        tot = lambda grp, c: sum(V[key(q)][c] for q in g[grp])  # noqa: E731
        # 1) 실전 덱별 딜과의 순위 상관
        rv = []
        byset = {frozenset(k.split(",")): k for k in sorted(V, key=lambda k: k in ov)}  # 같은 5명이면 랭커 순서(옛 값이 있는 키)
        for fs, ds in real[s].items():
            if fs in byset and len(ds) >= MIN_USERS:
                k = byset[fs]
                o = ov.get(k, {})
                rv.append({"deck": k, "n": len(ds), "real": st.median(ds), "L": V[k]["L"], "A": V[k]["A"],
                           "old": o.get("base"), "emu": o.get("rot")})
        cor = {c: spearman([r["real"] for r in rv if r[c] is not None], [r[c] for r in rv if r[c] is not None])
               for c in ("old", "emu", "L", "A")}
        # 2) 실전 대비 크게 낮은 덱
        sc = st.median(r["real"] / r["L"] for r in rv)
        for r in rv:
            r["under"] = r["real"] / r["L"] / sc
        low = sorted((r for r in rv if r["under"] >= LOW), key=lambda r: -r["under"])
        # 3) 랭커 대조(우리 A는 옛 지도 그대로, 다시 찾지 않음)
        vt = {c: tot("top_five", c) / tot("A", c) for c in ("L", "A")}
        vr1 = {c: tot("rank1", c) / tot("A", c) for c in ("L", "A")}
        vt_old = sum(ov[key(q)]["base"] for q in g["top_five"]) / sum(ov[key(q)]["base"] for q in g["A"])
        vt_emu = sum(ov[key(q)]["rot"] for q in g["top_five"]) / sum(ov[key(q)]["rot"] for q in g["A"])
        # 4) 지도 대표 덱: 옛 기록 값 → 새 L
        rep_ratio = [V[key(q)]["L"] / bk[frozenset(q)][0] for q in g["reps"]]
        # 5) 흉내와 실제 새 규칙의 일치(랭커 · A 덱)
        emu = [V[k]["L"] / ov[k]["rot"] for k in V if k in ov and ov[k]["rot"]]
        # 6) 레이어 의존
        la = [V[k]["L"] / V[k]["A"] for k in V if V[k]["A"]]
        row = {"season": s, "decks": len(V), "sims": d["sims"], "evaluator": d["evaluator"], "real_decks": len(rv), "corr": cor,
               "V_top": {"old": vt_old, "emu": vt_emu, **vt}, "V_r1": vr1,
               "reps_new_over_old": {"median": st.median(rep_ratio), "max": max(rep_ratio), "min": min(rep_ratio),
                                     "up10": sum(x >= 1.1 for x in rep_ratio), "n": len(rep_ratio)},
               "emu_match": {"n": len(emu), "same_0.1%": sum(abs(x - 1) < 1e-3 for x in emu), "median": st.median(emu),
                             "min": min(emu), "max": max(emu)},
               "layer": {"n": len(la), "median": st.median(la), "max": max(la), "min": min(la),
                         "gap5": sum(abs(x - 1) >= LAYER_GAP for x in la),
                         "top": sorted(([k, V[k]["L"] / V[k]["A"]] for k in V if V[k]["A"]), key=lambda x: -abs(x[1] - 1))[:5]},
               "low": [{k2: r[k2] for k2 in ("deck", "n", "real", "L", "A", "under")} for r in low], "real_rows": rv}
        rows.append(row)
    summ = {"corr_median": {c: st.median(r["corr"][c] for r in rows if r["corr"][c] is not None) for c in ("old", "emu", "L", "A")},
            "V_top_median": {c: st.median(r["V_top"][c] for r in rows) for c in ("old", "emu", "L", "A")},
            "sims": sum(r["sims"] for r in rows)}
    low_names = defaultdict(int)
    for r in rows:
        for x in r["low"]:
            for n in x["deck"].split(","):
                low_names[n] += 1
    summ["low_names"] = sorted(low_names.items(), key=lambda x: -x[1])[:20]
    (HERE / "r0.json").write_text(json.dumps({"summary": summ, "seasons": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    p = lambda x: "—" if x is None else f"{x:.2f}"  # noqa: E731
    q = lambda x: f"{x:.1%}"  # noqa: E731
    md.append("| 시즌 | 덱 | 실전 덱 | 상관 옛 · 흉내 · L · A | V_top 옛 · 흉내 · L · A | 대표 덱 새/옛 중앙(최대) | 흉내 일치 | L/A 5%+ | 낮은 덱 |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        c, v, e, la = r["corr"], r["V_top"], r["emu_match"], r["layer"]
        md.append(f"| S{r['season']} | {r['decks']} | {r['real_decks']} | {p(c['old'])} · {p(c['emu'])} · {p(c['L'])} · {p(c['A'])} | "
                  f"{q(v['old'])} · {q(v['emu'])} · {q(v['L'])} · {q(v['A'])} | {r['reps_new_over_old']['median']:.3f} "
                  f"({r['reps_new_over_old']['max']:.2f}) | {e['same_0.1%']}/{e['n']} | {la['gap5']}/{la['n']} | {len(r['low'])} |")
    (HERE / "r0.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    print("\n".join(md))
    return 0


def cmd_p0() -> int:
    """정정(R1 v1에서 발견): A(`operation.auto`)는 장비 옵션까지 뺀다. 같은 덱을 P0(레이어 켬 + 컨트롤 축 전부 끔)으로 다시 잰다."""
    import r1
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    with make_evaluator("rust", jobs=4, cache=False) as ev:
        for s in run31.SEASONS:
            f = OUT / f"S{s}.json"
            d = json.loads(f.read_text(encoding="utf-8"))
            if all("P0" in v for v in d["vals"].values()):
                continue
            ks = list(d["vals"])
            res = ev.evaluate([EvalRequest(k.split(","), boss=None, options=r1.p_base(s, k.split(","))) for k in ks])
            for k, r in zip(ks, res):
                d["vals"][k]["P0"] = None if r.total_damage is None else r.total_damage / E8
            d["sims_p0"] = len(ks)
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({"season": s, "sims": ev.sim_count}), flush=True)
    rows, all_lp, all_pa = [], [], []
    for s in run31.SEASONS:
        V = json.loads((OUT / f"S{s}.json").read_text(encoding="utf-8"))["vals"]
        lp = [v["L"] / v["P0"] for v in V.values() if v["P0"] and v["L"]]
        pa = [v["P0"] / v["A"] for v in V.values() if v["P0"] and v["A"]]
        all_lp += lp
        all_pa += pa
        rows.append({"season": s, "n": len(lp), "L/P0_median": st.median(lp), "L/P0_gap5": sum(abs(x - 1) >= LAYER_GAP for x in lp),
                     "P0/A_median": st.median(pa), "P0/A_gap5": sum(abs(x - 1) >= LAYER_GAP for x in pa)})
    out = {"rows": rows, "L/P0_gap5": sum(abs(x - 1) >= LAYER_GAP for x in all_lp), "P0/A_gap5": sum(abs(x - 1) >= LAYER_GAP for x in all_pa),
           "n": len(all_lp), "L/P0_range": [min(all_lp), max(all_lp)], "P0/A_range": [min(all_pa), max(all_pa)]}
    (HERE / "r0_p0.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if (sys.argv[1:] or [""])[0] == "p0":
        sys.exit(cmd_p0())
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        sys.exit(cmd_run())
    if cmd == "analyze":
        sys.exit(cmd_analyze(Path(sys.argv[2] if len(sys.argv) > 2 else "/home/user/jgaram/nikke-analysis")))
    print(__doc__)
    sys.exit(2)
