"""실험 32 R3b — B′ 비열등 재검증(README §R3b 사전 등록).

    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3b.py run --season 36 --seed 0,1
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3b.py end      # 끝 탐침(4시즌)
    source .cache/evaluators.env && python -I experiments/32_primitive_control/r3b.py post     # 5덱 후처리 + 흔들림
    python -I experiments/32_primitive_control/r3b.py maps                                     # 지도(시뮬 0)
    python -I experiments/32_primitive_control/r3b.py analyze                                  # → r3b.json · r3b.md

B′  사전 계산 = R3 A와 같은 절차(실험 10 `run_method` G+E, 시드 s0 · s1 × 12,500)에서 덱 평가만 P0(R1 `p_base`, 사람 규칙 없음) 1시뮬.
    끝 탐침 = 두 시드 기록을 합친 book에서 「5덱 묶음 이웃」 구성 200개 × 탐침 4(R3 종류 순위) — 덱 값 = 바탕 · 탐침 중 최고.
    후처리 = R3 B와 같다(원시 메뉴 v3 작은 축, 버스트는 이긴 탐침 고정, M3:k2 400).
A   R3 기록 그대로(사전 계산 · 후처리 · 지도). 새로 돌리지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import statistics as st
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import r3  # noqa: E402
from r3 import r1, r0, run31, M, R9, R10, R30, SIM, E8, jdump, jload  # noqa: E402

OUT = HERE / "r3b"
ARM = "Bp"
N_END = 200            # 끝 탐침 구성 수(× 탐침 4 = 800시뮬, 사전 계산의 약 3%)
PER_SLOT = 8           # 한 바퀴에 5덱 자리마다 다음 대안 수
DELTA = 0.01           # 비열등 허용 오차(사용자: 추천대로)
DEDICATED = ("미란다", "토브", "에이다", "아인")   # R3에서 B가 놓친 전담 규칙형(레이어 대상 중)
KEEP = 0.5             # 전담 규칙형: 지도 대표 등장 수 4시즌 합 ≥ A의 50%


def sdir(s: int) -> Path:
    return OUT / f"S{s}"


# ---------------------------------------------------------------- 사전 계산: 덱 평가 = P0 1시뮬

class P0Session(R9.Session):
    """실험 9 Session과 같은 기록 · 예산 규칙, 요청 options만 P0(니케마다 컨트롤 축 끔)."""

    def __init__(self, acct: Any, ev: Any, budget: int, season: int):
        super().__init__(acct, ev, budget)
        self.season = season

    def run(self, squads, phase: str, cap: int | None = None) -> int:
        from nikke_opt.evaluator import EvalRequest
        room = self.left if cap is None else min(self.left, cap)
        todo = [sq for sq in dict.fromkeys(squads) if sq not in self.asked][:max(room, 0)]
        if not todo:
            return 0
        res = self.ev.evaluate([EvalRequest(sq, boss=None, options=r1.p_base(self.season, sq)) for sq in todo])
        for sq, r in zip(todo, res):
            self.asked.add(sq)
            dmg = None if r.error else r.total_damage
            if dmg is not None:
                self.book.add(sq, dmg / E8)
            self.records.append({"squad": list(sq), "total_damage": dmg, "phase": phase, "error": r.error, "cached": r.cached})
        self.used += len(todo)
        return len(todo)


def run_pre(s: int, seed: int, ev: Any) -> dict[str, Any]:
    out_dir = sdir(s)
    f = out_dir / f"{ARM}_s{seed}.json"
    if f.exists():
        return jload(f)
    out_dir.mkdir(parents=True, exist_ok=True)
    acct = run31.account(s, seed)
    sims0 = ev.sim_count
    orig = R9.Session
    R9.Session = lambda a, e, b: P0Session(a, e, b, s)   # run_method 안의 R9.Session(acct, ev, budget)
    try:
        summ, recs, sess = R10.run_method(acct, "G+E", run31.SEED_BUDGET, ev, pool=177)
    finally:
        R9.Session = orig
    R30.write_recs(out_dir / f"{ARM}_s{seed}.jsonl.gz", recs)
    out = {"season": s, "arm": ARM, "seed": seed, "evals": summ["evals"], "records": len(recs), "sims": ev.sim_count - sims0,
           "seconds": summ["seconds"], "best": summ["final"]["total"], "errors": summ["errors"], "kicks": len(summ["kicks"]),
           "history": summ["history"], "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    jdump(f, out)
    print(json.dumps({k: v for k, v in out.items() if k != "history"}, ensure_ascii=False), flush=True)
    return out


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            for k in [int(x) for x in str(a.seed).split(",")]:
                run_pre(s, k, ev)
    return 0


# ---------------------------------------------------------------- 끝 탐침: 5덱 묶음 이웃 200 × 4

def recs_of(s: int) -> list[dict[str, Any]]:
    return [r for k in run31.SEEDS for r in R30.load_recs(sdir(s) / f"{ARM}_s{k}.jsonl.gz")]


def end_pick(order: Sequence[frozenset], cur: Mapping[frozenset, tuple[float, tuple]], probed: set,
             room: int) -> list[frozenset]:
    """지금 book의 최선 5덱(탐침 안 한 것) + 자리마다 「나머지 4덱과 겹치지 않는」 대안 중 바탕 값 상위 PER_SLOT개."""
    _, ch = R9.pack_vals(cur)
    five = [frozenset(q) for _, q in ch]
    pick = [c for c in five if c not in probed]
    for i in range(len(five)):
        others = frozenset().union(*(five[j] for j in range(len(five)) if j != i))
        n = 0
        for c in order:
            if n >= PER_SLOT:
                break
            if c in probed or c in pick or c & others:
                continue
            pick.append(c)
            n += 1
    return pick[:room]


def end_probe(s: int, ev: Any) -> dict[str, Any]:
    from nikke_opt.evaluator import EvalRequest
    f = sdir(s) / "end.json"
    if f.exists():
        return jload(f)
    base, _ = r3.book_win(recs_of(s))
    order = sorted(base, key=lambda c: (-base[c][0], base[c][1]))
    cur = dict(base)
    rows: dict[frozenset, dict[str, Any]] = {}
    n0, t0, rnd = ev.sim_count, time.time(), 0
    while len(rows) < N_END:
        pick = end_pick(order, cur, set(rows), N_END - len(rows))
        if not pick:
            break
        jobs = [(c, t, o) for c in pick for t, o in r3.probes(s, base[c][1])]
        res = ev.evaluate([EvalRequest(base[c][1], boss=None, options=o) for c, _, o in jobs])
        for c in pick:
            rows[c] = {"squad": list(base[c][1]), "base": base[c][0], "probes": [], "win": None, "round": rnd}
        for (c, t, _), r in zip(jobs, res):
            v = None if r.error else r.total_damage / E8
            x = rows[c]
            x["probes"].append([t, v])
            if v is not None and v > cur[c][0]:
                cur[c], x["win"] = (v, base[c][1]), t
        rnd += 1
    out = {"season": s, "rounds": rnd, "comps": len(rows), "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1),
           "errors": sum(v is None for x in rows.values() for _, v in x["probes"]), "rows": list(rows.values())}
    jdump(f, out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False), flush=True)
    return out


def cmd_end(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            end_probe(s, ev)
    return 0


def book_end(s: int) -> tuple[dict, dict]:
    """사전 계산 book(P0 값)에 끝 탐침 최고를 반영한 book + 구성 → 이긴 탐침."""
    bk, _ = r3.book_win(recs_of(s))
    win: dict[frozenset, str | None] = {}
    for x in jload(sdir(s) / "end.json")["rows"]:
        if x["win"]:
            c = frozenset(x["squad"])
            v = max(v for _, v in x["probes"] if v is not None)
            bk[c], win[c] = (v, tuple(x["squad"])), x["win"]
    return bk, win


def best5(s: int) -> list[dict[str, Any]]:
    bk, win = book_end(s)
    _, ch = R9.pack_vals(bk)
    return [{"id": f"r3b-S{s}-{ARM}-{i}", "season": s, "squad": list(q), "value": v, "win": win.get(frozenset(q))}
            for i, (v, q) in enumerate(ch)]


# ---------------------------------------------------------------- 후처리(R3 B와 같은 메뉴 · 예산)

def post_one(d: Mapping[str, Any], ev: Any, tag: str = "") -> dict[str, Any]:
    f = sdir(d["season"]) / "post" / f"{d['id']}{tag}.json"
    if f.exists():
        return jload(f)
    sp = r3.small_space(d["season"], d["squad"], d["win"])
    log = f.with_suffix(".jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    run = M.Run({"id": d["id"], "squad": list(d["squad"])}, sp, ev, method=f"{ARM}:{r3.SPEC}", budget=r3.BUDGET, out=log)
    t0 = time.time()
    try:
        M.m3(run, kick=2, seed=M.job_seed(d["id"] + tag, r3.SPEC))
    finally:
        run.close()
    raw = log.read_bytes()
    with gzip.open(log.with_suffix(".jsonl.gz"), "wb") as g:
        g.write(raw)
    log.unlink()
    errs = sum(1 for ln in raw.decode().splitlines() if json.loads(ln)["error"])
    out = {**d, "arm": ARM, "tag": tag, "evals": run.used, "errors": errs, "best": run.best / E8, "base": run.base_damage / E8,
           "best_variants": list(sp.labels(run.best_sel)), "keys": sp.K, "options": sp.nv, "seconds": round(time.time() - t0, 1)}
    jdump(f, out)
    return out


def cmd_post(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    lock = threading.Lock()
    t0 = time.time()
    with make_evaluator("rust", jobs=a.jobs, cache=False) as ev:
        jobs = []
        for s in [int(x) for x in str(a.season).split(",")]:
            ds = best5(s)
            jdump(sdir(s) / f"best5_{ARM}.json", ds)
            jobs += [(d, "") for d in ds] + [(ds[0], "-rep")]   # 흔들림: 최선 덱 하나를 다른 탐색 시드로 한 번 더

        def job(x):
            d, tag = x
            r = post_one(d, ev, tag)
            with lock:
                print(json.dumps({"id": d["id"] + tag, "evals": r["evals"], "errors": r["errors"], "gain": round(r["best"] / r["base"], 4),
                                  "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
        with ThreadPoolExecutor(a.workers) as pool:
            list(pool.map(job, jobs))
    return 0


# ---------------------------------------------------------------- 지도 · 분석(시뮬 0)

def _map_job(s: int) -> int:
    f = sdir(s) / f"map_{ARM}.json"
    if not f.exists():
        bk, _ = book_end(s)
        jdump(f, R30.class_map(bk))
    return s


def cmd_maps(a: argparse.Namespace) -> int:
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(a.workers) as pool:
        for s in pool.map(_map_job, [int(x) for x in str(a.season).split(",")]):
            print(s, flush=True)
    return 0


def map_counts(m: Mapping[str, Any], names: Sequence[str]) -> dict[str, int]:
    reps = [r for r in m["reps"] if not r.get("below")]
    c = collections.Counter(n for r in reps for q in r["decks"] for n in q)
    return {n: c.get(n, 0) for n in names} | {"_reps": len(reps)}


def cmd_analyze(a: argparse.Namespace) -> int:
    targets = r1.layer_targets()
    rows = []
    for s in r3.SEASONS:
        rk = run31.ranker_decks(s)
        top = [list(q) for q in rk["top_five"]]
        A5 = jload(r3.sdir(s) / "best5_A.json")
        Apost = [jload(r3.sdir(s) / "post" / f"{d['id']}.json") for d in A5]
        B5 = jload(r3.sdir(s) / "best5_B.json")
        Bpost = [jload(r3.sdir(s) / "post" / f"{d['id']}.json") for d in B5]
        P5 = jload(sdir(s) / f"best5_{ARM}.json") or best5(s)
        Ppost = [jload(sdir(s) / "post" / f"{d['id']}.json") for d in P5]
        rep = jload(sdir(s) / "post" / f"{P5[0]['id']}-rep.json")
        pre = {k: jload(sdir(s) / f"{ARM}_s{k}.json") for k in run31.SEEDS}
        end = jload(sdir(s) / "end.json") or {}
        bk0, _ = r3.book_win(recs_of(s))
        row: dict[str, Any] = {
            "season": s,
            "A_post": sum(p["best"] for p in Apost), "B_post": sum(p["best"] for p in Bpost),
            "Bp_post": sum(p["best"] for p in Ppost) if all(Ppost) else None,
            "A_pre": sum(d["value"] for d in A5), "Bp_pre": sum(d["value"] for d in P5),
            "Bp_pre_noend": R9.pack_vals(bk0)[0],
            "Bp_seed_pack": {k: R9.pack_vals(r3.book_win(R30.load_recs(sdir(s) / f"{ARM}_s{k}.jsonl.gz"))[0])[0] for k in run31.SEEDS},
            "sims_pre": sum(p["sims"] for p in pre.values() if p), "comps": len(bk0),
            "end": {k: end.get(k) for k in ("rounds", "comps", "sims", "errors")},
            "end_wins": sum(1 for x in end.get("rows", []) if x["win"]),
            "five": [{"squad": d["squad"], "value": d["value"], "win": d["win"], "post": p and p["best"],
                      "variants": p and p["best_variants"]} for d, p in zip(P5, Ppost)],
            "post_sims": sum(p["evals"] for p in Ppost if p),
            "rep_post": None if not rep else {"best": rep["best"], "first": Ppost[0]["best"] if Ppost[0] else None},
            "J_top": {"A": SIM.pair_jaccard(top, [d["squad"] for d in A5]), "Bp": SIM.pair_jaccard(top, [d["squad"] for d in P5])},
            "targets_in_five": {"A": sorted({n for d in A5 for n in d["squad"]} & set(targets)),
                                "Bp": sorted({n for d in P5 for n in d["squad"]} & set(targets))},
        }
        if row["Bp_post"]:
            row["ratio"] = row["Bp_post"] / row["A_post"] - 1
        mA, mP = jload(r3.sdir(s) / "map_A.json"), jload(sdir(s) / f"map_{ARM}.json")
        if mA and mP:
            row["map"] = {"A": map_counts(mA, targets), "Bp": map_counts(mP, targets)}
        rows.append(row)
    summ: dict[str, Any] = {}
    if all(r.get("ratio") is not None for r in rows):
        rs = [r["ratio"] for r in rows]
        summ = {"ratio_median": st.median(rs), "ratio": rs, "sum_ok": st.median(rs) >= -DELTA}
    if all("map" in r for r in rows):
        ded = {n: {"A": sum(r["map"]["A"][n] for r in rows), "Bp": sum(r["map"]["Bp"][n] for r in rows)} for n in DEDICATED}
        for n, x in ded.items():
            x["ok"] = x["A"] == 0 or x["Bp"] >= KEEP * x["A"]
        summ["dedicated"] = ded
        summ["dedicated_ok"] = all(x["ok"] for x in ded.values())
    if "sum_ok" in summ and "dedicated_ok" in summ:
        summ["verdict"] = "B′ 비열등" if summ["sum_ok"] and summ["dedicated_ok"] else "B′ 미달"
    jdump(HERE / "r3b.json", {"summary": summ, "seasons": rows})
    pc = lambda x: "—" if x is None else f"{x:+.2%}"  # noqa: E731
    md = ["| 시즌 | A 5덱(후처리) | B′ 5덱(후처리) | B′/A − 1 | B′ 사전 5덱(끝 탐침 전 → 뒤) | A 사전 5덱 | 끝 탐침 이긴 구성 | J A · B′ |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| S{r['season']} | {r['A_post']:.2f} | {r['Bp_post'] or 0:.2f} | {pc(r.get('ratio'))} | "
                  f"{r['Bp_pre_noend']:.2f} → {r['Bp_pre']:.2f} | {r['A_pre']:.2f} | {r['end_wins']}/{r['end']['comps']} | "
                  f"{r['J_top']['A']:.2f} · {r['J_top']['Bp']:.2f} |")
    if "dedicated" in summ:
        md += ["", "| 전담 규칙형 | 지도 대표 등장 A | B′ | 기준(A의 50%) |", "|---|---|---|---|"]
        md += [f"| {n} | {x['A']} | {x['Bp']} | {'통과' if x['ok'] else '미달'} |" for n, x in summ["dedicated"].items()]
    if "verdict" in summ:
        md += ["", f"판단: 5덱 합 중앙 {summ['ratio_median']:+.2%}(기준 ≥ −{DELTA:.0%}) · 전담 규칙형 "
                   f"{'통과' if summ['dedicated_ok'] else '미달'} → **{summ['verdict']}**"]
    (HERE / "r3b.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("run", "end", "post", "maps", "analyze"))
    p.add_argument("--season", default=",".join(map(str, r3.SEASONS)))
    p.add_argument("--seed", default="0,1")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    return {"run": cmd_run, "end": cmd_end, "post": cmd_post, "maps": cmd_maps, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
