"""실험 26 — θ = 0.2 대안 근처 짧은 탐색: 실험 20 개발 계정 12개의 계정 탐색 기록(U4_3000)에 「대안 쪽」 탐색 1,000평가를 더한다.

    source .cache/evaluators.env && python experiments/26_alt_local/run26.py run [--only t1,t2]
        → run_log/<계정>.json(요약) · .jsonl.gz(새 평가 기록)
    python experiments/26_alt_local/run26.py analyze      → results.md · analysis.json(시뮬 없음)

- 출발: 실험 24와 같은 기록 · 같은 고르기 — 기록의 최선 5덱과 J ≤ 0.2인 5덱 중 합 최대(기본 레이어).
- 탐색 한 라운드(100평가): 그때 기록에서 다시 고른 J ≤ 0.2 대안 5덱을
  (1) 5덱 고치기(실험 4 `pack_moves`: 한 명 바꾸기 · 두 덱 사이 맞교환) 70%, (2) 대안 덱의 이웃(한 명 바꾸기) 30%로 고친다.
  고친 뒤의 5덱도 최선과 J ≤ 0.2여야 한다. 순서는 대리 모델(실험 10 `DualFit`)의 예상 이득 순이다.
- 끝의 1/8(125평가)은 마지막 대안 덱의 배치 순서 다듬기(실험 10과 같은 `distinct_orders`)에 쓴다.
- 대조(시뮬 없음): 같은 계정의 계정 탐색 U4_4000(평소 탐색에 1,000평가 더) 기록에서 같은 고르기.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
LOG = HERE / "run_log"
ACC20 = EXPS / "20_search_robust" / "run_log" / "accounts"
sys.path.insert(0, str(EXPS / "20_search_robust"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R20 = sys.modules.get("run20") or _load("run20", EXPS / "20_search_robust" / "run20.py")
P24 = sys.modules.get("pick24") or _load("pick24", EXPS / "24_diverse_pick" / "pick24.py")
AC, R10, R9 = R20.AC, R20.R10, R20.R9
S4, R2 = R9.S4, R9.R2
SIM = P24.SIM
E8 = 1e8

THETA = 0.2                 # README §사전 등록
BASE_RUN, CONTROL_RUN = "U4_3000", "U4_4000"
EXTRA = 1000
CHECK = 500                 # 중간 확인(관찰)
ROUND = 100
RESERVE = EXTRA // 8        # 배치 순서 다듬기
FIX_SHARE = 0.7
PACK_LIMIT = 120.0          # J 상한 묶기 제한 시간(초) — 넘으면 찾은 해를 쓰고 표시한다
GOOD, BAD = 0.97, 0.95


def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in R20.A20.dev_scenarios() if not only or s["id"] in only.split(",")}


def jpick(book: Mapping[frozenset, tuple[float, tuple]], theta: float = THETA,
          prev: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """기록의 최선과, 최선과 J ≤ θ인 5덱 중 합 최대(실험 24 `constrained`의 정확해 쪽 · 제한 시간 넘으면 찾은 해).
    prev(직전 결과)의 최선이 그대로면 직전 대안이 여전히 가능한 해라 그 합을 floor로 넘긴다 — 더 큰 해가 없으면 직전 대안(결과 같음)."""
    tot, best = R9.pack_vals(book)
    bd = [frozenset(q) for _, q in best]
    cost = P24.pair_cost(book, bd)
    b = P24.budget_of(theta)
    floor, keep = None, None
    if prev and prev.get("decks") and {frozenset(q) for q in prev["best"]} == set(bd):
        keep = [book[frozenset(q)] for q in prev["decks"]]
        floor = 0.0
        for v, _ in keep:
            floor += v
    exact = True                           # floor 탐색이 끝나면 직전 대안이 최적이라는 증명이기도 하다
    try:
        t, d = R9.pack_vals(book, cost=cost, budget=b, floor=floor, deadline=time.monotonic() + PACK_LIMIT)
    except R9.PackTimeout as e:
        t, d, exact = e.total, e.decks, False
    if keep is not None and (not d or t <= floor):
        t, d = floor, keep
    return {"best_total": tot, "best": [list(q) for _, q in best], "total": t, "decks": [list(q) for _, q in d],
            "exact": exact, "budget": b}


def describe(book: Mapping[frozenset, tuple[float, tuple]], p: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: p[k] for k in ("best_total", "total", "exact")}
    if not p["decks"]:
        return {**out, "found": False}
    bd = {frozenset(q) for q in p["best"]}
    new = [frozenset(q) for q in p["decks"] if frozenset(q) not in bd]
    return {**out, "found": True, "ratio": p["total"] / p["best_total"], **SIM.compare(p["best"], p["decks"]),
            "neighbors": [P24.neighbors(book, c) for c in new], "decks": p["decks"], "best": p["best"]}


def plan_cost(decks: Sequence[Sequence[str]], best: Sequence[frozenset]) -> int:
    return sum(sum(len(frozenset(d) & b) * (len(frozenset(d) & b) - 1) // 2 for b in best) for d in decks)


def apply_move(decks: Sequence[tuple], new: Sequence[tuple]) -> list[tuple]:
    """pack_moves의 새 스쿼드가 대신하는 덱(같은 니케가 가장 많은 덱)을 바꾼 5덱."""
    out = list(decks)
    for sq in new:
        i = max(range(len(out)), key=lambda j: len(set(out[j]) & set(sq)))
        out[i] = sq
    return out


def targeted_round(sess: Any, n: int, fitf: Any, theta: float = THETA, prev: Mapping[str, Any] | None = None
                   ) -> tuple[list[tuple], dict[str, Any]]:
    """J ≤ θ 대안 5덱을 고치는 후보 n개(README §절차). 그때의 고르기 결과도 돌려준다."""
    book = sess.book.best
    p = jpick(book, theta, prev)
    if not p["decks"]:
        return [], p
    best = [frozenset(q) for q in p["best"]]
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
        if plan_cost(apply_move(decks, new), best) <= p["budget"]:
            got += take(new)
    used = {x for d in decks for x in d}
    cands = []
    for i, d in enumerate(decks):
        rest = decks[:i] + decks[i + 1:]
        for nb in S4.neighbors(d, {k: v for k, v in acct.owned.items() if k not in used or k in d}):
            if frozenset(nb) in book or plan_cost(rest + [nb], best) > p["budget"]:
                continue
            cands.append((score(frozenset(nb)) - score(frozenset(d)), nb))
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick, p


def preload(sess: Any, records: Sequence[Mapping[str, Any]]) -> None:
    """기존 기록을 세션에 넣는다(시뮬 없음, 같은 요청은 다시 묻지 않는다)."""
    for r in records:
        sq = tuple(r["squad"])
        sess.asked.add(sq)
        if r["total_damage"] is not None:
            sess.book.add(sq, r["total_damage"] / E8)


def run_account(acct: Any, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    fitf = R10.fit_for(177)
    burst = R10.BURST_ALL
    base_recs = R9.load_records(ACC20 / f"{acct.id}_{BASE_RUN}.jsonl.gz")
    sess = R9.Session(acct, ev, EXTRA)
    preload(sess, base_recs)
    t0, sims0 = time.time(), ev.sim_count
    p = jpick(sess.book.best)
    start = describe(sess.book.best, p)
    history, check = [], None
    while sess.left > RESERVE:
        n = min(ROUND, sess.left - RESERVE, CHECK - sess.used if sess.used < CHECK else ROUND)
        pick, p = targeted_round(sess, n, fitf, prev=p)
        history.append({"evals": sess.used, "alt": p["total"], "best": p["best_total"], "exact": p["exact"]})
        if not pick or not sess.run(pick, f"대안 탐색 {len(history)}", cap=n):
            break
        if check is None and sess.used >= CHECK:
            p = jpick(sess.book.best, prev=p)
            check = describe(sess.book.best, p)
            check["evals"] = sess.used
    p = jpick(sess.book.best, prev=p)
    orders = list(dict.fromkeys(o for q in p["decks"] for o in R2.distinct_orders(tuple(sess.book.best[frozenset(q)][1]), burst)
                                if sess.fresh(o)))
    sess.run(orders, "순서", cap=sess.left)
    final = describe(sess.book.best, jpick(sess.book.best, prev=p))
    final["evals"] = sess.used
    cbook = R9.book_of(R9.load_records(ACC20 / f"{acct.id}_{CONTROL_RUN}.jsonl.gz"))
    control = describe(cbook, jpick(cbook))
    summ = {"scenario": acct.id, "name": acct.name, "theta": THETA, "extra": EXTRA, "evals": sess.used,
            "errors": sum(r["error"] is not None for r in sess.records), "start": start, "check": check, "final": final,
            "control": control, "history": history, "sims_during": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1),
            "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    return summ, sess.records


def cmd_run(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    LOG.mkdir(parents=True, exist_ok=True)
    scs = scenarios(a.only)
    ev = make_evaluator()
    with ev:
        for sid, s in scs.items():
            if (LOG / f"{sid}.json").exists():
                continue
            summ, recs = run_account(AC.AccountT(s), ev)
            R10.write_run(LOG, sid, summ, recs)
            print(json.dumps({"scenario": sid, "start": round(summ["start"].get("ratio", 0), 4),
                              "final": round(summ["final"].get("ratio", 0), 4), "sims": summ["sims_during"],
                              "seconds": summ["seconds"]}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 분석(README §판단 기준)

def verdict(final: Sequence[float | None], control: Sequence[float | None]) -> str:
    rs = [r for r in final if r is not None]
    if len(rs) < len(final) or not rs:
        return "더 큰 보강 필요"
    med = statistics.median(rs)
    if med >= GOOD and sum(r >= GOOD for r in rs) * 4 >= 3 * len(rs):
        base = "짧은 탐색으로 충분"
    elif med < BAD:
        return "더 큰 보강 필요"
    else:
        base = "일부"
    cs = [c for c in control if c is not None]
    ahead = bool(cs) and med - statistics.median(cs) >= 0.005
    return f"{base} · {'대조보다 앞섬' if ahead else '대조와 비슷하거나 뒤짐'}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def cmd_analyze(a: argparse.Namespace) -> int:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LOG.glob("*.json"))]
    def r_of(x):
        return x.get("ratio") if x and x.get("found") else None
    fin, ctl = [r_of(r["final"]) for r in rows], [r_of(r["control"]) for r in rows]
    v = verdict(fin, ctl) if rows else "기록 없음"
    med = lambda xs: statistics.median([x for x in xs if x is not None]) if any(x is not None for x in xs) else None
    L = ["# 실험 26 결과 — θ = 0.2 대안 근처 짧은 탐색", "",
         "`python experiments/26_alt_local/run26.py analyze`가 만든다. 절차 · 기준은 [README](README.md).", "",
         f"**판단(사전 등록): {v}** — 계정 {len(rows)}개.", "",
         "- 값 비율 = 대안(J ≤ 0.2) 5덱 합 ÷ 같은 기록의 최선 5덱 합(기본 레이어, 후처리 전).",
         "- 출발 = 실험 24와 같은 기록(U4_3000). +500 · +1,000 = 대안 쪽 탐색 뒤. 대조 = 평소 계정 탐색 4,000(U4_4000).", "",
         "| 계정 | 출발 | +500 | +1,000 | 대조(U4_4000) | +1,000의 J · 바꿀 · 공유 | 새 덱 이웃 수(출발 → +1,000) | 새 시뮬 |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f = r["final"]
        nb0 = statistics.median(r["start"].get("neighbors") or [0])
        nb1 = statistics.median(f.get("neighbors") or [0])
        L.append(f"| {r['scenario']} | {pct(r_of(r['start']))} | {pct(r_of(r['check']))} | {pct(r_of(f))} | {pct(r_of(r['control']))} | "
                 f"{f.get('pair_jaccard', 0):.2f} · {f.get('moves', '—')} · {f.get('shared_nikkes', '—')} | {nb0:g} → {nb1:g} | {r['sims_during']} |")
    L += ["", f"중앙: 출발 {pct(med([r_of(r['start']) for r in rows]))} · +500 {pct(med([r_of(r['check']) for r in rows]))} · "
              f"+1,000 {pct(med(fin))} · 대조 {pct(med(ctl))}. 97% 이상: +1,000 {sum(1 for x in fin if x and x >= GOOD)}/{len(rows)} · "
              f"대조 {sum(1 for x in ctl if x and x >= GOOD)}/{len(rows)}. 새 시뮬 합 {sum(r['sims_during'] for r in rows)}.",
          ""]
    (HERE / "results.md").write_text("\n".join(L), encoding="utf-8")
    (HERE / "analysis.json").write_text(json.dumps({"verdict": v, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(v)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--only")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("analyze")
    p.set_defaults(func=cmd_analyze)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
