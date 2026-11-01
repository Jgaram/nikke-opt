"""실험 29 — 큰 분류 C(근처 탐색 + 후처리)와 보이는 세부 분류의 새 덱 후처리: 실험 28 계층을 시뮬로 채운다(w1~w8).

    source .cache/evaluators.env && python experiments/29_tree_post/run29.py run --only w1 --tag W1
        → run_log/<계정>.json(요약 · 계층) · .jsonl.gz(새 기본 레이어 평가) · run_log/ops/(이 실험에서 새로 돈 운용 탐색)
          · run_log/run_<tag>.jsonl(실행 기록, 세션마다 따로)
    python experiments/29_tree_post/run29.py analyze      → results.md · analysis.json(시뮬 없음, 현황판이 읽는다)

- A = 최선 5덱(실험 25 P 판), B = 실험 27 대안(후처리 뒤). 둘 다 고정이다.
- C 근처 탐색(실험 27 절차, 기준만 A · B 둘): 라운드(100평가)마다 A · B **둘 다와** J ≤ 0.2인 5덱 중 합 최대를 고르고
  (실험 28 `pick_far`), 5덱 고치기 70% · 대안 덱 이웃 30%로 고친다. 고친 뒤도 두 기준과 J ≤ 0.2. 끝 125평가는 배치 순서 다듬기.
- C 후처리: 늘어난 기록으로 고정점 후처리(`policy_pf(packer = 두 기준 pick_far)`). 출발 운용 값 = 실험 25 · 27 운용 기록 전부.
- 세부 분류 후처리: A · B · C 대표마다 실험 28 `subs` → `order_subs`의 보일 3개 중 운용 값이 없는 새 덱을 후처리하고
  다시 나열한다(최대 SUB_ROUNDS번, 계정당 새 덱 SUB_CAP개까지). 더보기는 그때 값 그대로(후처리 안 된 덱은 기본 레이어).
- 운용 탐색은 실험 27 → 25 기록에 있으면 다시 쓴다(결정론, 시뮬 0). 주력 딜러 개념은 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
LOG = HERE / "run_log"
EXP25, EXP27, EXP28 = EXPS / "25_jpick_alt", EXPS / "27_alt_local_check", EXPS / "28_plan_tree"
sys.path.insert(0, str(EXP25))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


T28 = sys.modules.get("tree28") or _load("tree28", EXP28 / "tree28.py")
R27 = T28.R27
R25, R26, R20, R18, R17, R10, R9, P24, SIM = R27.R25, R27.R26, R27.R20, R27.R18, R27.R17, R27.R10, R27.R9, R27.P24, R27.SIM
AC, R19, S4, R2 = R27.AC, R27.R19, R27.S4, R27.R2
E8 = 1e8
METHOD = R27.METHOD                  # JT 400(T@main)

THETA = T28.THETA_BIG                # 0.2 — 대표끼리
EXTRA, CHECK, ROUND = R27.EXTRA, R27.CHECK, R27.ROUND       # 1,000 · 500 · 100 (실험 26 · 27과 같다)
RESERVE, FIX_SHARE = R27.RESERVE, R27.FIX_SHARE             # 125 · 0.7
PACK_LIMIT = 120.0
ALT_RATIO, PASS_COUNT = 0.97, 6      # 실험 25 · 27과 같은 문턱(8개 중) — README §사전 등록
SUB_ROUNDS, SUB_CAP = 3, 16          # 세부 분류 후처리: 다시 나열 최대 3번, 계정당 새 덱 16개(≈ 6,400 시뮬)까지


def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in R25.A25.check_scenarios() if not only or s["id"] in only.split(",")}


def r27_of(sid: str) -> dict[str, Any]:
    return json.loads((EXP27 / "run_log" / f"{sid}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- C 고르기 · 고치기(기준 A · B 고정)

def vals_of(book: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float]) -> dict[frozenset, tuple[float, tuple]]:
    return {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in book.items()}


def pick_c(book: Mapping[frozenset, tuple[float, tuple]], refs: Sequence[Sequence[tuple]], post: Mapping[tuple, float],
           prev: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A · B 둘 다와 J ≤ θ인 5덱 중 max(기본, 운용 값) 합 최대(실험 28 `pick_far`).
    기준이 고정이라 직전 C는 늘 가능한 해다 — 시간 초과로 더 낮은 해가 나오면 직전 C를 그대로 쓴다."""
    vals = vals_of(book, post)
    p = T28.pick_far(vals, book, refs, THETA, PACK_LIMIT)
    out = {"found": p["found"], "exact": p.get("exact", False), "budget": P24.budget_of(THETA),
           "total": p.get("total", float("-inf")), "decks": [list(q) for _, q in p.get("decks", [])]}
    if prev and prev.get("decks"):
        keep = [vals[frozenset(q)] for q in prev["decks"]]
        floor = 0.0
        for v, _ in keep:
            floor += v
        if not p["found"] or out["total"] < floor:
            out.update(found=True, total=floor, decks=[list(q) for _, q in keep])
    return out


def within(decks: Sequence[Sequence[str]], refs: Sequence[Sequence[frozenset]], budget: int) -> bool:
    return all(R26.plan_cost(decks, r) <= budget for r in refs)


def targeted_round(sess: Any, n: int, fitf: Any, refs: Sequence[Sequence[tuple]], post: Mapping[tuple, float],
                   prev: Mapping[str, Any] | None = None) -> tuple[list[tuple], dict[str, Any]]:
    """실험 27 `targeted_round`와 같은 후보 만들기 — 고르기 · 고친 뒤 확인을 기준 둘(A · B)로 한다."""
    book = sess.book.best
    p = pick_c(book, refs, post, prev=prev)
    if not p["found"]:
        return [], p
    rs = [[frozenset(q) for q in r] for r in refs]
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
        if within(R26.apply_move(decks, new), rs, p["budget"]):
            got += take(new)
    used = {x for d in decks for x in d}
    cands = []
    for i, d in enumerate(decks):
        rest = decks[:i] + decks[i + 1:]
        for nb in S4.neighbors(d, {k: v for k, v in acct.owned.items() if k not in used or k in d}):
            if frozenset(nb) in book or not within(rest + [nb], rs, p["budget"]):
                continue
            cands.append((score(frozenset(nb)) - score(frozenset(d)), nb))
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick, p


def ratio_of(p: Mapping[str, Any], best: float) -> float | None:
    return p["total"] / best if p.get("found") else None


# ---------------------------------------------------------------- 계층(실험 28 정의, 대표 값 = 후처리 뒤)

def build_tree(best: float, reps: Mapping[str, Sequence[tuple[float, tuple]]], vals: Mapping[frozenset, tuple[float, tuple]],
               known: set) -> list[dict[str, Any]]:
    """큰 분류마다 실험 28 `subs` → `order_subs`. 세부 분류마다 다른 대표와의 J(`J_other`)를 붙인다."""
    floor = T28.GOOD * best
    plans = {k: [list(q) for _, q in rep] for k, rep in reps.items()}
    out = []
    for name, rep in reps.items():
        tot = 0.0
        for v, _ in rep:
            tot += v
        ss = T28.order_subs(T28.subs(rep, vals, known, floor))
        for s in ss[:T28.MORE]:
            kept = [list(rep[i][1]) for i in range(len(rep)) if i + 1 not in s["changed"]]
            plan = kept + s["new_decks"]
            s["J_other"] = {o: SIM.pair_jaccard(plans[o], plan) for o in reps if o != name}
        out.append({"name": name, "found": True, "total": tot, "ratio": tot / best, "decks": [[v, list(q)] for v, q in rep],
                    "subs_count": len(ss), "subs": ss[:T28.MORE], "subs_1deck": sum(len(s["changed"]) == 1 for s in ss)})
    return out


def shown_need(tree: Sequence[Mapping[str, Any]], vals: Mapping[frozenset, tuple[float, tuple]],
               post: Mapping[tuple, float]) -> list[tuple]:
    """보일 세부 분류(큰 분류마다 앞 SHOW개)의 새 덱 중 운용 값이 없는 것(순서 = 그 구성의 최선 배치)."""
    need: list[tuple] = []
    for k in tree:
        for s in k["subs"][:T28.SHOW]:
            for q in s["new_decks"]:
                sq = vals[frozenset(q)][1]
                if sq not in post and not R20.R16.has_test(sq) and sq not in need:
                    need.append(sq)
    return need


# ---------------------------------------------------------------- 운용 탐색(실험 27 · 25 기록 재사용)

class Ops29(R27.Ops27):
    """이 실험의 run_log/ops → 실험 27 → 실험 25 순으로 읽고, 없는 것만 돌려 이 실험의 run_log/ops에 쓴다."""

    def __init__(self, ev, accts, priors):
        super().__init__(ev, accts, priors)
        self.out = LOG / "ops"
        self.prevs = [EXP27 / "run_log" / "ops", EXP25 / "run_log" / "ops"]
        self.from_prev: dict[str, int] = defaultdict(int)

    def get_cached(self, m: str, cid: str) -> dict[str, Any] | None:
        r = R18.Ops.get_cached(self, m, cid)
        if r is None:
            for d in self.prevs:
                p = d / m / f"{R18.hname(cid)}.json"
                if p.exists():
                    r = json.loads(p.read_text(encoding="utf-8"))
                    self.memo[(m, cid)] = r
                    self.from_prev[d.parent.parent.name] += 1
                    break
        return r


def run_account(sid: str, acct: Any, ev: Any, ops: Ops29, pool: ThreadPoolExecutor) -> tuple[dict[str, Any], list]:
    def value_fn(squads):
        futs = {sq: pool.submit(ops.get, METHOD, sid, sq) for sq in squads}
        return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}

    t0 = time.time()
    p25, r27 = R27.plan25(sid), r27_of(sid)
    best = p25["total"]                              # 판정 기준(실험 25 · 27과 같은 P 판 최선)
    A = T28.plan_of(p25["decks"])
    B = T28.plan_of(r27["final"]["decks"])
    refs = [[q for _, q in A], [q for _, q in B]]
    acc = T28.account(sid)                           # 실험 25 + 27 기록 · 운용 값
    post0 = dict(acc["post"])
    # 1. C 근처 탐색(기본 레이어, 1,000평가)
    recs0 = R9.load_records(Path(f"{R25.run_file(sid)}.jsonl.gz")) + R9.load_records(EXP27 / "run_log" / f"{sid}.jsonl.gz")
    fitf = R10.fit_for(177)
    sess = R9.Session(acct, ev, EXTRA)
    R26.preload(sess, recs0)
    sims0 = ev.sim_count
    p = pick_c(sess.book.best, refs, post0)
    start = {"ratio": ratio_of(p, best), "exact": p["exact"], "decks": p["decks"]}
    history, check = [], None
    while sess.left > RESERVE:
        n = min(ROUND, sess.left - RESERVE, CHECK - sess.used if sess.used < CHECK else ROUND)
        pick, p = targeted_round(sess, n, fitf, refs, post0, prev=p)
        history.append({"evals": sess.used, "C": p["total"] / best if p["found"] else None, "exact": p["exact"]})
        if not pick or not sess.run(pick, f"C 탐색 {len(history)}", cap=n):
            break
        if check is None and sess.used >= CHECK:
            p = pick_c(sess.book.best, refs, post0, prev=p)
            check = {"ratio": ratio_of(p, best), "evals": sess.used}
    p = pick_c(sess.book.best, refs, post0, prev=p)
    if p["found"]:
        orders = list(dict.fromkeys(o for q in p["decks"]
                                    for o in R2.distinct_orders(tuple(sess.book.best[frozenset(q)][1]), R10.BURST_ALL)
                                    if sess.fresh(o)))
        sess.run(orders, "순서", cap=sess.left)
    pp = pick_c(sess.book.best, refs, post0, prev=p)
    pre_post = {"ratio": ratio_of(pp, best), "exact": pp["exact"], "evals": sess.used}
    search_sims = ev.sim_count - sims0
    # 2. C 후처리(두 기준 고르기 고정점)
    book1 = sess.book.best
    s1, ran1 = ev.sim_count, sum(ops.ran.values())
    exacts: list[bool] = []

    def packer(post):
        q = pick_c(book1, refs, post)
        exacts.append(q["exact"])
        vals = vals_of(book1, post)
        return q["total"], [vals[frozenset(d)] for d in q["decks"]]

    cr = R20.policy_pf(book1, value_fn, post=dict(post0), packer=packer)
    post = cr["post"]
    C = [(float(v), tuple(sq)) for v, sq in cr["decks"]]
    c_final = {"total": cr["total"], "ratio": cr["total"] / best, "decks": cr["decks"],
               "J_A": SIM.pair_jaccard(refs[0], [list(q) for _, q in C]), "J_B": SIM.pair_jaccard(refs[1], [list(q) for _, q in C]),
               **{f"vs_A_{k}": v for k, v in SIM.compare(refs[0], [list(q) for _, q in C]).items()},
               "post_comps": len(cr["ran"]), "rounds": cr["rounds"], "post_new_runs": sum(ops.ran.values()) - ran1,
               "pick_timeouts": sum(not e for e in exacts), "sims": ev.sim_count - s1}
    best_after = R18.pack(book1, post)[0]
    # 3. 세부 분류 후처리: 보일 3개의 새 덱 → 다시 나열(고정점, 최대 SUB_ROUNDS번 · 새 덱 SUB_CAP개)
    reps = {"A": A, "B": B, "C": C}
    s2, ran2 = ev.sim_count, sum(ops.ran.values())
    sub_rounds, sub_posted, converged = 0, [], False
    while True:
        vals = vals_of(book1, post)
        known = {c for c, (_, sq) in book1.items() if sq in post}
        tree = build_tree(best, reps, vals, known)
        need = shown_need(tree, vals, post)
        if not need:
            converged = True
            break
        if sub_rounds >= SUB_ROUNDS or len(sub_posted) >= SUB_CAP:
            break
        need = need[:SUB_CAP - len(sub_posted)]
        post.update(value_fn(need))
        sub_posted += need
        sub_rounds += 1
    notes = {"A": "최선(실험 25 P 판, 후처리 뒤)", "B": "실험 27 대안(후처리 뒤)", "C": "근처 탐색 + 후처리 뒤(이 실험)"}
    for k in tree:
        k["note"] = notes[k["name"]]
        k["shown_unposted"] = sum(s["new_unposted"] for s in k["subs"][:T28.SHOW])
    rep_J = {f"{a}-{b}": SIM.pair_jaccard([list(q) for _, q in reps[a]], [list(q) for _, q in reps[b]])
             for a, b in combinations("ABC", 2)}
    summ = {"scenario": sid, "name": acct.name, "best": best, "best_after": best_after,
            "C_start": start, "C_check": check, "C_pre_post": pre_post, "C_final": c_final, "C_history": history,
            "evals": sess.used, "errors": sum(x["error"] is not None for x in sess.records), "requests": len(sess.records),
            "search_sims": search_sims,
            "subs_post": {"rounds": sub_rounds, "posted": [list(sq) for sq in sub_posted], "converged": converged,
                          "new_runs": sum(ops.ran.values()) - ran2, "sims": ev.sim_count - s2},
            "classes": tree, "rep_J": rep_J, "seconds": round(time.time() - t0, 1),
            "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    return summ, sess.records


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    LOG.mkdir(parents=True, exist_ok=True)
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    ev = make_evaluator()
    ops = Ops29(ev, accts, priors)
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
            cl = {k["name"]: k for k in summ["classes"]}
            print(json.dumps({"scenario": sid, "C_pre_post": summ["C_pre_post"]["ratio"], "C_final": round(summ["C_final"]["ratio"], 4),
                              "subs": [cl[x]["subs_count"] for x in "ABC"], "subs_post": summ["subs_post"]["sims"],
                              "sims": ev.sim_count, "t": round(time.time() - t0)}, ensure_ascii=False), flush=True)
        pool.shutdown()
        with (LOG / f"run_{a.tag}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "run", "only": a.only, "tag": a.tag, "runs": done,
                                "sims": ev.sim_count, "cache_hits": ev.cache_hits, "ops_ran": dict(ops.ran),
                                "ops_from_prev": dict(ops.from_prev), "seconds": round(time.time() - t0),
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
    t28 = {r["scenario"]: r for r in json.loads((EXP28 / "analysis.json").read_text(encoding="utf-8"))["rows"]}
    cfin = [r["C_final"]["ratio"] for r in rows]
    v = verdict(cfin) if rows else "기록 없음"
    med = lambda xs: statistics.median(xs) if xs else None
    short = T28.short
    L = ["# 실험 29 결과 — 큰 분류 C(근처 탐색 + 후처리) · 세부 분류 후처리(w1~w8)", "",
         "`python experiments/29_tree_post/run29.py analyze`가 만든다. 절차 · 기준은 [README](README.md).", "",
         f"**판단(사전 등록): {v}** — 후처리 뒤 C 합 ≥ 실험 25 최선(P 판)의 {ALT_RATIO:.0%}인 계정이 {PASS_COUNT}개 이상이면 통과.", "",
         "## 계정별 요약", "",
         "| 계정 | 실험 28 C(후처리 전, 기록만) | 탐색 전 | +1,000(후처리 전) | **C 후처리 뒤** | J (A-C · B-C) | 세부 분류 ≥ 97% (A · B · C) | 새 시뮬(탐색 · C 후처리 · 세부 후처리) |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cl = {k["name"]: k for k in r["classes"]}
        c28 = {k["name"]: k for k in t28.get(r["scenario"], {}).get("classes", [])}.get("C", {})
        f = r["C_final"]
        L.append(f"| {r['scenario']} | {pct(c28.get('ratio'))} | {pct(r['C_start']['ratio'])} | {pct(r['C_pre_post']['ratio'])} | "
                 f"**{pct(f['ratio'])}** | {r['rep_J']['A-C']:.2f} · {r['rep_J']['B-C']:.2f} | "
                 f"{cl['A']['subs_count']} · {cl['B']['subs_count']} · {cl['C']['subs_count']} | "
                 f"{r['search_sims']} · {f['sims']} · {r['subs_post']['sims']} |")
    if rows:
        L += ["", f"C 후처리 뒤: 중앙 {pct(med(cfin))}, 최소 {pct(min(cfin))}, 97% 이상 {sum(x >= ALT_RATIO for x in cfin)}/{len(rows)}. "
                  f"새 시뮬 합 {sum(r['search_sims'] + r['C_final']['sims'] + r['subs_post']['sims'] for r in rows)}.", ""]
    for r in rows:
        L += [f"## {r['scenario']} (최선 {r['best']:.1f}억) — {r['name']}", ""]
        for k in r["classes"]:
            L += [f"### 큰 분류 {k['name']} — {pct(k['ratio'])} · {k['note']}", ""]
            for i, (val, q) in enumerate(k["decks"]):
                L.append(f"{i + 1}. {val:.1f}억 — " + " · ".join(short(x) for x in q))
            L += ["", f"세부 분류 {k['subs_count']}개. 위 {T28.SHOW}개는 바뀐 덱이 겹치지 않게 고른 것(새 덱 후처리), 더보기는 합 순:", "",
                  "| # | 합 | J | 다른 대표와 J | 바뀐 덱 | 빠짐 → 들어옴 | 후처리 안 된 새 덱 |", "|---|---|---|---|---|---|---|"]
            for i, s in enumerate(k["subs"]):
                tag = "" if i < T28.SHOW else " (더보기)"
                swap = (" · ".join(short(x) for x in s["out"]) + " → " + " · ".join(short(x) for x in s["in"])) if s["in"] else "같은 니케 · 덱 사이 옮김"
                jo = " · ".join(f"{o} {j:.2f}" for o, j in s["J_other"].items())
                L.append(f"| {i + 1}{tag} | {pct(s['total'] / r['best'])} | {s['J']:.2f} | {jo} | {', '.join(map(str, s['changed']))}덱 | {swap} | {s['new_unposted']} |")
            L.append("")
    (HERE / "results.md").write_text("\n".join(L), encoding="utf-8")
    (HERE / "analysis.json").write_text(json.dumps({"verdict": v, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(v)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--only")
    p.add_argument("--tag", default="M")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("analyze")
    p.set_defaults(func=cmd_analyze)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
