"""실험 27 — J ≤ 0.2 대안 + 대안 근처 1,000평가 탐색 + 후처리: 실험 25 계정 w1~w8에서 확인한다.

    source .cache/evaluators.env && python experiments/27_alt_local_check/run27.py run [--only w1,w2]
        → run_log/<계정>.json(요약) · .jsonl.gz(새 기본 레이어 평가) · run_log/ops/(이 실험에서 새로 돈 운용 탐색)
    python experiments/27_alt_local_check/run27.py analyze      → results.md · analysis.json(시뮬 없음)

- 최선: 실험 25 P 판 그대로(계정 탐색 U4_3000 → 5덱 고정점 후처리 JT 400). 실험 25 운용 기록으로 다시 돌려
  같은 5덱 · 같은 합이 나오는지 확인한다(시뮬 0).
- 대안 근처 탐색(실험 26 절차): 기준 = **후처리 뒤 최선 5덱(고정)**. 라운드(100평가)마다 그때 기록에서
  최선과 J ≤ 0.2인 5덱 중 합 최대(값 = max(기본 레이어, 알려진 운용 값))를 고르고, 실험 26 `targeted_round`처럼
  5덱 고치기 70% · 대안 덱 이웃 30%로 고친다. 끝 125평가는 대안 덱 배치 순서 다듬기.
- 후처리: 늘어난 기록으로 실험 25와 같은 J 상한 묶기 고정점 후처리(`policy_pf(packer = jpacker(θ = 0.2))`).
  출발 운용 값은 최선 후처리의 것(실험 25 θ = 0.2 대안과 같은 출발). 주력 딜러 개념은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
LOG = HERE / "run_log"
EXP25 = EXPS / "25_jpick_alt"
sys.path.insert(0, str(EXP25))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R25 = sys.modules.get("run25") or _load("run25", EXP25 / "run25.py")
R26 = sys.modules.get("run26") or _load("run26", EXPS / "26_alt_local" / "run26.py")
R20, R18, R17, R10, R9, P24, SIM = R25.R20, R25.R18, R25.R17, R25.R10, R25.R9, R25.P24, R25.SIM
AC, R19, S4, R2 = R25.AC, R25.R19, R26.S4, R26.R2
E8 = 1e8
METHOD = R25.METHOD                 # JT 400(T@main)

THETA = 0.2                         # README §사전 등록
EXTRA, CHECK, ROUND = R26.EXTRA, R26.CHECK, R26.ROUND       # 1,000 · 500 · 100 (실험 26과 같다)
RESERVE, FIX_SHARE = R26.RESERVE, R26.FIX_SHARE             # 125 · 0.7
PACK_LIMIT = 120.0                  # 탐색 중 고르기 제한 시간(초) — 실험 26과 같다
ALT_RATIO, PASS_COUNT = 0.97, 6     # 실험 25와 같은 문턱(8개 중)
BASE_THETA_02 = "0.2"               # 비교: 실험 25의 탐색 없는 θ = 0.2 대안


def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in R25.A25.check_scenarios() if not only or s["id"] in only.split(",")}


def plan25(sid: str) -> dict[str, Any]:
    p = EXP25 / "run_log" / f"plans_{sid}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()][-1]


# ---------------------------------------------------------------- 고르기(기준 5덱 고정)

def jpick_fixed(book: Mapping[frozenset, tuple[float, tuple]], bdecks: Sequence[Sequence[str]],
                post: Mapping[tuple, float], theta: float = THETA, prev: Mapping[str, Any] | None = None
                ) -> dict[str, Any]:
    """고정한 최선 5덱(bdecks)과 J ≤ θ인 겹치지 않는 5덱 중 max(기본, 운용 값) 합 최대.
    기준이 고정이라 직전 대안은 늘 가능한 해다 — 그 합을 floor로 넘겨 빠르게 찾는다(결과 같음)."""
    bd = [frozenset(q) for q in bdecks]
    vals = {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in book.items()}
    cost = P24.pair_cost(book, bd)
    b = P24.budget_of(theta)
    floor, keep = None, None
    if prev and prev.get("decks"):
        keep = [vals[frozenset(q)] for q in prev["decks"]]
        floor = 0.0
        for v, _ in keep:
            floor += v
    exact = True
    try:
        t, d = R9.pack_vals(vals, cost=cost, budget=b, floor=floor, deadline=time.monotonic() + PACK_LIMIT)
    except R9.PackTimeout as e:
        t, d, exact = e.total, e.decks, False
    if keep is not None and (not d or t <= floor):
        t, d = floor, keep
    return {"best": [list(q) for q in bdecks], "total": t, "decks": [list(q) for _, q in d], "exact": exact, "budget": b}


def targeted_round(sess: Any, n: int, fitf: Any, bdecks: Sequence[Sequence[str]], post: Mapping[tuple, float],
                   prev: Mapping[str, Any] | None = None) -> tuple[list[tuple], dict[str, Any]]:
    """실험 26 `targeted_round`와 같은 후보 만들기 — 고르기만 고정 기준(`jpick_fixed`)이다."""
    book = sess.book.best
    p = jpick_fixed(book, bdecks, post, prev=prev)
    if not p["decks"]:
        return [], p
    best = [frozenset(q) for q in bdecks]
    decks = [tuple(book[frozenset(q)][1]) for q in p["decks"]]
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = R9._take_factory(sess, pick, seen, n)
    share = int(n * FIX_SHARE)
    got = 0
    for _, new in S4.pack_moves(decks, acct.owned, score):
        if got >= share:
            break
        if R26.plan_cost(R26.apply_move(decks, new), best) <= p["budget"]:
            got += take(new)
    used = {x for d in decks for x in d}
    cands = []
    for i, d in enumerate(decks):
        rest = decks[:i] + decks[i + 1:]
        for nb in S4.neighbors(d, {k: v for k, v in acct.owned.items() if k not in used or k in d}):
            if frozenset(nb) in book or R26.plan_cost(rest + [nb], best) > p["budget"]:
                continue
            cands.append((score(frozenset(nb)) - score(frozenset(d)), nb))
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick, p


def describe(book: Mapping[frozenset, tuple[float, tuple]], p: Mapping[str, Any], ref_total: float) -> dict[str, Any]:
    if not p["decks"]:
        return {"found": False, "total": p["total"]}
    bd = {frozenset(q) for q in p["best"]}
    new = [frozenset(q) for q in p["decks"] if frozenset(q) not in bd]
    return {"found": True, "total": p["total"], "exact": p["exact"], "ratio": p["total"] / ref_total,
            **SIM.compare(p["best"], p["decks"]), "neighbors": [P24.neighbors(book, c) for c in new], "decks": p["decks"]}


# ---------------------------------------------------------------- 운용 탐색(실험 25 기록 재사용)

class Ops27(R25.Ops25):
    """실험 25 운용 기록(run_log/ops)을 먼저 읽고, 없는 것만 돌려 이 실험의 run_log/ops에 쓴다(값은 결정론)."""

    def __init__(self, ev, accts, priors):
        super().__init__(ev, accts, priors)
        self.out = LOG / "ops"
        self.prev = EXP25 / "run_log" / "ops"
        self.from25 = 0

    def get_cached(self, m: str, cid: str) -> dict[str, Any] | None:
        r = super().get_cached(m, cid)
        if r is None:
            p = self.prev / m / f"{R18.hname(cid)}.json"
            if p.exists():
                r = json.loads(p.read_text(encoding="utf-8"))
                self.memo[(m, cid)] = r
                self.from25 += 1
        return r


def run_account(sid: str, acct: Any, ev: Any, ops: Ops27, pool: ThreadPoolExecutor) -> tuple[dict[str, Any], list]:
    def value_fn(squads):
        futs = {sq: pool.submit(ops.get, METHOD, sid, sq) for sq in squads}
        return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}

    def settings(decks) -> dict[str, Any]:
        return {">".join(sq): (ops.get_cached(METHOD, R17.comp_id(sid, sq)) or {}).get("labels") for _, sq in decks}

    t0 = time.time()
    p25 = plan25(sid)
    base_recs = R9.load_records(Path(f"{R25.run_file(sid)}.jsonl.gz"))
    book0 = R9.book_of(base_recs)
    # 1. 최선 다시 만들기(실험 25 운용 기록 → 시뮬 0이어야 한다)
    s0 = ev.sim_count
    r = R20.policy_pf(book0, value_fn)
    post = r.pop("post")
    bdecks = [list(sq) for _, sq in r["decks"]]
    repro = {"total": r["total"], "same_decks": [sorted(q) for q in bdecks] == [sorted(q) for _, q in p25["decks"]],
             "total_diff": r["total"] - p25["total"], "sims": ev.sim_count - s0}
    best_total = p25["total"]                        # 판정 기준(실험 25와 같은 P 판 최선)
    # 2. 대안 근처 탐색(기본 레이어, 1,000평가)
    fitf = R10.fit_for(177)
    sess = R9.Session(acct, ev, EXTRA)
    R26.preload(sess, base_recs)
    sims0 = ev.sim_count
    p = jpick_fixed(sess.book.best, bdecks, post)
    start = describe(sess.book.best, p, best_total)
    history, check = [], None
    while sess.left > RESERVE:
        n = min(ROUND, sess.left - RESERVE, CHECK - sess.used if sess.used < CHECK else ROUND)
        pick, p = targeted_round(sess, n, fitf, bdecks, post, prev=p)
        history.append({"evals": sess.used, "alt": p["total"], "exact": p["exact"]})
        if not pick or not sess.run(pick, f"대안 탐색 {len(history)}", cap=n):
            break
        if check is None and sess.used >= CHECK:
            p = jpick_fixed(sess.book.best, bdecks, post, prev=p)
            check = describe(sess.book.best, p, best_total)
            check["evals"] = sess.used
    p = jpick_fixed(sess.book.best, bdecks, post, prev=p)
    orders = list(dict.fromkeys(o for q in p["decks"]
                                for o in R2.distinct_orders(tuple(sess.book.best[frozenset(q)][1]), R10.BURST_ALL)
                                if sess.fresh(o)))
    sess.run(orders, "순서", cap=sess.left)
    pre_post = describe(sess.book.best, jpick_fixed(sess.book.best, bdecks, post, prev=p), best_total)
    pre_post["evals"] = sess.used
    search_sims = ev.sim_count - sims0
    # 3. 후처리(실험 25와 같은 J 상한 묶기 고정점)
    book1 = sess.book.best
    flags: dict[str, Any] = {}
    s1, ran0 = ev.sim_count, sum(ops.ran.values())
    ar = R20.policy_pf(book1, value_fn, post=dict(post), packer=R25.jpacker(book1, [tuple(q) for q in bdecks], THETA, flags))
    adecks = [(v, tuple(sq)) for v, sq in ar["decks"]]
    best_after = R18.pack(book1, ar["post"])[0]
    final = {"total": ar["total"], "decks": ar["decks"], "ratio": ar["total"] / best_total,
             "ratio_vs_best_after": ar["total"] / max(best_total, best_after),
             **SIM.compare(bdecks, [list(sq) for _, sq in adecks]),
             "post_comps": len(ar["ran"]), "post_evals": len(ar["ran"]) * R18.BUDGET["T"], "rounds": ar["rounds"],
             "post_new_runs": sum(ops.ran.values()) - ran0, "best_after_alt": best_after,
             "timeouts": flags.get("timeouts", 0), "sims": ev.sim_count - s1, "settings": settings(adecks)}
    summ = {"scenario": sid, "name": acct.name, "theta": THETA, "extra": EXTRA, "best_total": best_total,
            "best_decks": bdecks, "repro": repro, "base25": p25["alts"][BASE_THETA_02], "start": start, "check": check,
            "pre_post": pre_post, "final": final, "history": history, "evals": sess.used,
            "errors": sum(x["error"] is not None for x in sess.records), "requests": len(sess.records),
            "search_sims": search_sims, "seconds": round(time.time() - t0, 1),
            "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    return summ, sess.records


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    LOG.mkdir(parents=True, exist_ok=True)
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    ev = make_evaluator()
    ops = Ops27(ev, accts, priors)
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()
    done = []
    with ev:
        for sid in scs:
            if (LOG / f"{sid}.json").exists():
                continue
            summ, recs = run_account(sid, accts[sid], ev, ops, pool)
            R10.write_run(LOG, sid, summ, recs)
            done.append(sid)
            print(json.dumps({"scenario": sid, "repro": summ["repro"], "start": round(summ["start"].get("ratio", 0), 4),
                              "pre_post": round(summ["pre_post"].get("ratio", 0), 4), "final": round(summ["final"]["ratio"], 4),
                              "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
        pool.shutdown()
        with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "run", "only": a.only, "runs": done,
                                "sims": ev.sim_count, "cache_hits": ev.cache_hits, "ops_ran": dict(ops.ran),
                                "ops_from25": ops.from25, "seconds": round(time.time() - t0),
                                "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"},
                               ensure_ascii=False) + "\n")
    return 0


# ---------------------------------------------------------------- 분석(README §판단 기준)

def verdict(ratios: Sequence[float | None]) -> str:
    ok = sum(1 for r in ratios if r is not None and r >= ALT_RATIO)
    return f"통과 ({ok}/{len(ratios)})" if ok >= PASS_COUNT else f"미통과 ({ok}/{len(ratios)})"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def cmd_analyze(a: argparse.Namespace) -> int:
    rows = [json.loads((LOG / f"{s['id']}.json").read_text(encoding="utf-8"))
            for s in R25.A25.check_scenarios() if (LOG / f"{s['id']}.json").exists()]
    fin = [r["final"]["ratio"] for r in rows]
    v = verdict(fin) if rows else "기록 없음"
    v2 = verdict([r["final"]["ratio_vs_best_after"] for r in rows]) if rows else "기록 없음"
    med = lambda xs: statistics.median(xs) if xs else None
    L = ["# 실험 27 결과 — J ≤ 0.2 대안 + 대안 근처 1,000평가 + 후처리(w1~w8)", "",
         "`python experiments/27_alt_local_check/run27.py analyze`가 만든다. 절차 · 기준은 [README](README.md).", "",
         f"**판단(사전 등록): {v}** — 후처리 뒤 J ≤ 0.2 대안 합 ≥ 실험 25 최선(P 판)의 {ALT_RATIO:.0%}인 계정이 {PASS_COUNT}개 이상이면 통과.",
         f"관찰: 대안 쪽에서 오른 최선 기준으로 다시 재면 {v2}.", "",
         "| 계정 | 실험 25 θ = 0.2(탐색 없음) | 탐색 전 | +500 | +1,000(후처리 전) | **+1,000 · 후처리 뒤** | J · 바꿀 · 공유 | 오른 최선 | 새 시뮬(탐색 · 후처리) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f = r["final"]
        up = f["best_after_alt"] / r["best_total"] - 1
        mark = " (시간 초과)" if f.get("timeouts") else ""
        L.append(f"| {r['scenario']} | {pct(r['base25']['ratio'])} | {pct(r['start'].get('ratio'))} | {pct((r['check'] or {}).get('ratio'))} | "
                 f"{pct(r['pre_post'].get('ratio'))} | **{pct(f['ratio'])}**{mark} | {f['pair_jaccard']:.2f} · {f['moves']} · {f['shared_nikkes']} | "
                 f"{up * 100:+.2f}% | {r['search_sims']} · {f['sims']} |")
    if rows:
        b25 = [r["base25"]["ratio"] for r in rows]
        L += ["", f"중앙: 실험 25 θ = 0.2 {pct(med(b25))}({sum(x >= ALT_RATIO for x in b25)}/{len(rows)}) → 후처리 뒤 {pct(med(fin))} "
                  f"(최소 {pct(min(fin))}, 97% 이상 {sum(x >= ALT_RATIO for x in fin)}/{len(rows)}). "
                  f"J 중앙 {med([r['final']['pair_jaccard'] for r in rows]):.2f}.",
              f"새 시뮬 합: 탐색 {sum(r['search_sims'] for r in rows)} · 후처리 {sum(r['final']['sims'] for r in rows)}. "
              f"최선 다시 만들기: {sum(r['repro']['same_decks'] for r in rows)}/{len(rows)}개 같은 5덱, 시뮬 {sum(r['repro']['sims'] for r in rows)}."]
    L.append("")
    (HERE / "results.md").write_text("\n".join(L), encoding="utf-8")
    (HERE / "analysis.json").write_text(json.dumps({"verdict": v, "verdict_vs_best_after": v2, "rows": rows},
                                                   ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(v)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--only")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("analyze")
    p.set_defaults(func=cmd_analyze)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
