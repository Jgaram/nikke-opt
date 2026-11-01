"""실험 20 — 계정 탐색 보강(덱 여러 개 재배분 누락) · 주력 딜러 배분이 다른 유력 대안 (README §방법 · §판).

    source .cache/evaluators.env && python experiments/20_search_robust/run20.py search [--only d1] [--runs U4_4000]
        → run_log/accounts/<계정>_<탐색>.json · .jsonl.gz(실험 10 형식). t 계정의 U4_2000 · U4_4000은 실험 19 기록을 쓴다
    source .cache/evaluators.env && python experiments/20_search_robust/run20.py post [--only d1]
        → run_log/ops/T@main/<해시>.json(구성마다 운용 탐색) · run_log/plans_<계정>.jsonl(계정 × 판 결과 + 유력 대안)

- 계정 탐색: 실험 13 U4 흐름(L0)을 예산 2,000 · 3,000 · 4,000으로(U4_*), 그리고 같은 흐름을 두 계보로 나눈 CL(아래 `run_two`).
- 후처리: 실험 19 절차 그대로 — 5덱 고정점(PF) · JT 400(실험 19 배포 사전값 main, 기법 이름 T@main).
- 주력 딜러: 덱(구성의 최선 순서)을 계정 기본 레이어로 평가한 결과에서 딜 1위 니케(평가기 `members`, 캐시 적중이라 시뮬 없음).
- 유력 대안(2026-11-01 사용자 결정 「주력 딜러 배분이 다른 안」): 최선 5덱의 주력 딜러 5명 중 2명이 주력이 되는 구성을 빼고 다시 짠 최선
  (10쌍 중 최고) — 주력 딜러가 최선과 다른 덱이 2개 이상이다. 그 대안의 덱에도 같은 후처리(고정점)를 돌리고, 5덱 합이 최선의 97% 이상이면 「유력」.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
LOG = HERE / "run_log"
sys.path.insert(0, str(HERE))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import accounts20 as A20  # noqa: E402

AC = A20.AC
R19 = sys.modules.get("run19") or _load("run19", EXPS / "19_first_goal" / "run19.py")
R18, R17, R10, R9 = R19.R18, R19.R17, R19.R10, R19.R9
R16 = R18.R16
E8 = R19.E8

RUNS = {"U4_2000": ("P", 2000), "U4_3000": ("P", 3000), "U4_4000": ("P", 4000), "CL_3000": ("CL", 3000)}
REUSE19 = ("U4_2000", "U4_4000")     # t 계정은 실험 19 계정 탐색 기록을 그대로 쓴다
SPLIT = 0.5                          # CL: 첫 계보(U4 출발)에 탐색 예산의 절반, 나머지는 두 번째 계보
PLANS = (("C0", "U4_2000"), ("C3", "U4_3000"), ("CL3", "CL_3000"), ("REF", "U4_4000"))
ALT_PLANS = ("C0", "C3", "CL3")
ALT_RATIO = 0.97
METHOD = "T@main"                    # 실험 19 P와 같은 운용 탐색(JT 400 · 배포 사전값 main)


def run_file(sid: str, run: str) -> Path:
    if sid.startswith("t") and run in REUSE19:
        return R19.LOG / "accounts" / f"{sid}_{run}"
    return LOG / "accounts" / f"{sid}_{run}"


def load_book(sid: str, run: str) -> dict[frozenset, tuple[float, tuple]]:
    return R9.book_of(R9.load_records(Path(f"{run_file(sid, run)}.jsonl.gz")))


def load_summary(sid: str, run: str) -> dict[str, Any]:
    return json.loads(Path(f"{run_file(sid, run)}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 주력 딜러 · 유력 대안

def leader_of_raw(raw: Mapping[str, Any]) -> str | None:
    members = raw.get("members") or []
    if not members:
        return None
    return max(members, key=lambda m: (m.get("damage") or 0, m["name"]))["name"]


def leaders_of(acct: Any, ev: Any, squads: Sequence[tuple]) -> dict[tuple, str | None]:
    """구성마다 계정 기본 레이어 평가의 딜 1위(계정 탐색이 이미 평가한 요청이라 캐시 적중)."""
    from nikke_opt.evaluator import EvalRequest
    squads = list(dict.fromkeys(tuple(s) for s in squads))
    res = ev.evaluate([EvalRequest(sq, boss=None, options=acct.options) for sq in squads])
    return {sq: (None if r.error else leader_of_raw(r.raw)) for sq, r in zip(squads, res)}


def leader_alt(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float],
               lead_best: Sequence[str | None], leader: Mapping[frozenset, str | None]
               ) -> tuple[float, list[tuple[float, tuple]], tuple[str, str] | None]:
    """최선 5덱의 주력 딜러 중 두 명(a, b)이 주력인 구성을 빼고 다시 짠 최선 — 10쌍 중 합이 가장 큰 것.
    값이 같으면 앞선 쌍(이름 순). 대안의 주력 딜러 중 최선과 다른 사람이 2명 이상이 된다."""
    names = sorted({x for x in lead_best if x})
    out: tuple[float, list[tuple[float, tuple]], tuple[str, str] | None] = (0.0, [], None)
    for a, b in combinations(names, 2):
        vals = {c: v for c, v in best.items() if leader.get(c) not in (a, b)}
        t, d = R18.pack(vals, post, floor=out[0] if out[1] else None)   # 앞 쌍보다 큰 해만(결과 같음, 빠름)
        if d and t > out[0]:
            out = (t, d, (a, b))
    return out


REBUILD_SHARE = 4   # 최선 덱과 이만큼 이상 겹치면 「그 덱을 고친 덱」, 아니면 「다시 짠 덱」


def rebuild_alt(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float],
                best_decks: Sequence[tuple], leader: Mapping[frozenset, str | None]
                ) -> tuple[float, list[tuple[float, tuple]], tuple[int, int] | None]:
    """다듬은 유력 대안(실험 20 결과를 보고 더한 측정, README §결과): 최선 덱 두 개(i, j)마다 — 그 두 덱과 4명 이상 겹치는 구성과
    그 두 덱의 주력 딜러가 주력인 구성을 빼고 다시 짠 최선 — 10쌍 중 합이 가장 큰 것.
    그러면 대안에는 「다시 짠 덱」(최선의 어느 덱과도 4명 이상 겹치지 않는 덱)이 2개 이상, 주력 딜러가 최선과 다른 덱이 2개 이상 있다."""
    bd = [frozenset(sq) for sq in best_decks]
    lead = [leader.get(c) for c in bd]
    out: tuple[float, list[tuple[float, tuple]], tuple[int, int] | None] = (0.0, [], None)
    for i, j in combinations(range(len(bd)), 2):
        bad = {lead[i], lead[j]} - {None}
        vals = {c: v for c, v in best.items()
                if leader.get(c) not in bad and len(c & bd[i]) < REBUILD_SHARE and len(c & bd[j]) < REBUILD_SHARE}
        t, d = R18.pack(vals, post, floor=out[0] if out[1] else None)   # 앞 쌍보다 큰 해만(결과 같음, 빠름)
        if d and t > out[0]:
            out = (t, d, (i, j))
    return out


def alt_shape(best_decks: Sequence[tuple], alt_decks: Sequence[tuple], leader: Mapping[frozenset, str | None]
              ) -> dict[str, int]:
    """대안의 모양: 다시 짠 덱 수 · 주력 딜러가 최선 주력 5명 밖인 덱 수 · 공유 니케 수."""
    bd = [frozenset(sq) for sq in best_decks]
    ad = [frozenset(sq) for sq in alt_decks]
    lb = {leader.get(c) for c in bd}
    return {"rebuilt": sum(1 for c in ad if max((len(c & b) for b in bd), default=0) < REBUILD_SHARE),
            "new_leaders": sum(1 for c in ad if leader.get(c) not in lb),
            "shared_nikkes": len(set().union(*bd) & set().union(*ad)) if bd and ad else 0}


def policy_pf(best: Mapping[frozenset, tuple[float, tuple]], value: Callable[[Sequence[tuple]], Mapping[tuple, float]],
              post: dict[tuple, float] | None = None,
              packer: Callable[[Mapping[tuple, float]], tuple[float, list]] | None = None) -> dict[str, Any]:
    """실험 18 PF(5덱 고정점)과 같다 — 운용 값 사전(post)도 돌려준다. packer를 주면 그 묶기로 고정점을 돈다(대안)."""
    post = {} if post is None else post
    pk = packer or (lambda p: R18.pack(best, p))
    ran: list[tuple] = []
    skipped: set[tuple] = set()
    rounds = 0
    while rounds < R18.MAX_ROUNDS:
        _, decks = pk(post)[:2]
        need = [sq for _, sq in decks if sq not in post and sq not in skipped]
        skipped.update(sq for sq in need if R16.has_test(sq))
        need = [sq for sq in need if not R16.has_test(sq)]
        if not need:
            break
        post.update(value(need))
        ran += need
        rounds += 1
    res = pk(post)
    return {"total": res[0], "decks": [[v, list(sq)] for v, sq in res[1]], "ran": ran, "rounds": rounds,
            "post": post, "extra": res[2:] }


# ---------------------------------------------------------------- 두 계보 계정 탐색(CL)

class LeaderSession(R9.Session):
    """실험 9 Session과 같되 평가마다 주력 딜러(딜 1위)를 기록한다."""

    def __init__(self, acct: Any, ev: Any, budget: int):
        super().__init__(acct, ev, budget)
        self.leader: dict[tuple, str | None] = {}

    def run(self, squads, phase: str, cap: int | None = None) -> int:
        from nikke_opt.evaluator import EvalRequest
        room = self.left if cap is None else min(self.left, cap)
        todo = [sq for sq in dict.fromkeys(squads) if sq not in self.asked][:max(room, 0)]
        if not todo:
            return 0
        res = self.ev.evaluate([EvalRequest(sq, boss=None, options=self.acct.options) for sq in todo])
        for sq, r in zip(todo, res):
            self.asked.add(sq)
            dmg = None if r.error else r.total_damage
            lead = None
            if dmg is not None:
                self.book.add(sq, dmg / E8)
                lead = self.leader[sq] = leader_of_raw(r.raw)
            self.records.append({"squad": list(sq), "total_damage": dmg, "phase": phase,
                                 "error": r.error, "cached": r.cached, "leader": lead})
        self.used += len(todo)
        return len(todo)


def run_two(acct: Any, budget: int, ev: Any, pre: Mapping[str, Any], split: float = SPLIT, pool: int = 177
            ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """CL: 실험 13 U4 흐름(L0)을 탐색 예산의 split까지 돈 뒤(첫 계보 — U4 · 같은 예산 실행의 앞부분과 같다),
    그때의 최선 5덱과 주력 딜러 배분이 다른 최선(`leader_alt`)에서 두 번째 계보를 시작해 나머지 예산을 그 계보 안에서 국소 탐색한다.
    끝에 두 계보 최선의 배치 순서를 다듬고 전체 기록에서 5덱을 짠다."""
    fitf = R10.fit_for(pool)
    burst = R10.BURST_ALL
    sess = LeaderSession(acct, ev, budget)
    t0, sims0 = time.time(), ev.sim_count
    reserve = budget // 8
    decks = [d for s in pre["sets"] for d in R10.transplant_coef([tuple(x) for x in s], acct.owned, pre["coef"], burst)]
    sess.run(decks, "옮기기", cap=budget - reserve)
    a_end = int((budget - reserve) * split)
    history = [{"evals": sess.used, "pack": sess.pack()[0], "lineage": "A"}]
    while sess.left > reserve and sess.used < a_end:
        n = min(R10.ROUND, sess.left - reserve)
        pick = R10.local_round(sess, n, None, fitf)
        if not pick or not sess.run(pick, f"탐색 {len(history)}", cap=n):
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0], "lineage": "A"})
    a_best = sess.pack()
    lead = {c: sess.leader.get(sq) for c, (_, sq) in sess.book.best.items()}
    lead_best = [lead.get(frozenset(sq)) for _, sq in a_best[1]]
    bt, bd, pair = leader_alt(sess.book.best, {}, lead_best, lead)
    lineage = {frozenset(sq) for _, sq in bd} if bd else None
    b_start = {"evals": sess.used, "pack": bt, "pair": list(pair) if pair else None,
               "leaders_a": lead_best, "leaders_b": [lead.get(frozenset(sq)) for _, sq in bd]}
    while sess.left > reserve:
        n = min(R10.ROUND, sess.left - reserve)
        pick = R10.local_round(sess, n, lineage, fitf)
        if not pick or not sess.run(pick, f"탐색 {len(history)}", cap=n):
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0], "lineage": "B" if lineage else "A",
                        "b_pack": R10.lineage_pack(sess, lineage) if lineage else None})
    pre_order = {"evals": sess.used, "pack": sess.pack()[0]}
    best = sess.pack()
    bpack = R9.pack_vals({c: v for c, v in sess.book.best.items() if c in lineage}) if lineage else (0.0, [])
    tops = ([sq for _, sq in best[1]] + [sq for _, sq in bpack[1]]
            + [sq for _, sq in sorted(sess.book.best.values(), reverse=True)[:R9.ORDER_TOP]])
    orders = list(dict.fromkeys(p for sq in dict.fromkeys(tops) for p in R10.R2.distinct_orders(sq, burst)
                                if sess.fresh(p)))
    sess.run(orders, "순서")
    final = sess.pack()
    history.append({"evals": sess.used, "pack": final[0], "lineage": "order"})
    fsq = [sq for _, sq in final[1]]
    bfin = R9.pack_vals({c: v for c, v in sess.book.best.items() if lineage and c in lineage}) if lineage else (0.0, [])
    summ = {"scenario": acct.id, "name": acct.name, "pool": pool, "method": "CL", "budget": budget, "split": split,
            "evals": sess.used, "errors": sum(r["error"] is not None for r in sess.records),
            "a_end": a_end, "b_start": b_start, "history": history, "pre_order": pre_order,
            "final": R10.pack_dict(final), "b_final": R10.pack_dict(bfin, fsq),
            "lineage_b": len(lineage or ()), "sims_during": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1)}
    return summ, sess.records


# ---------------------------------------------------------------- 실행 명령

def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in A20.dev_scenarios() if not only or s["id"] in only.split(",")}


def log_run(rec: Mapping[str, Any]) -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_search(a: argparse.Namespace) -> int:
    scs = scenarios(a.only)
    runs = a.runs.split(",") if a.runs else list(RUNS)
    out = LOG / "accounts"
    out.mkdir(parents=True, exist_ok=True)
    pre = json.loads(R19.PRE["U4"].read_text(encoding="utf-8"))
    R10.pack_alt20 = lambda *x, **k: (0.0, [])   # 실험 11 · 13 · 19와 같다
    tasks = [(sid, run) for run in sorted(runs, key=lambda r: -RUNS[r][1]) for sid in scs
             if not Path(f"{run_file(sid, run)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    with ev:
        for sid, run in tasks:
            acct = AC.AccountT(scs[sid])
            kind, b = RUNS[run]
            if kind == "P":
                summ, recs, _ = R10.run_method(acct, "P", b, ev, pre=pre, pool=177)
                summ.pop("alt20", None)
            else:
                summ, recs = run_two(acct, b, ev, pre)
            summ.update(run=run, scenario=sid)
            R10.write_run(out, f"{sid}_{run}", summ, recs)
            print(json.dumps({"run": f"{sid}_{run}", "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "search", "only": a.only, "runs": [f"{s}_{r}" for s, r in tasks],
               "sims": ev.sim_count, "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    log_run(rec)
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


class Ops20(R19.Ops19):
    """실험 19 Ops19와 같고, 이 실험에 없는 결과는 실험 19 기록(같은 계정 · 같은 구성 · 같은 기법)을 읽는다(t 계정)."""

    def __init__(self, ev: Any, accts: Mapping[str, Any], priors: Mapping[str, Mapping[str, list[str]]]):
        super().__init__(ev, accts, priors)
        self.out = LOG / "ops"

    def get_cached(self, m: str, cid: str) -> dict[str, Any] | None:
        r = super().get_cached(m, cid)
        if r is None:
            p = R19.LOG / "ops" / m / f"{R18.hname(cid)}.json"
            if p.exists():
                r = json.loads(p.read_text(encoding="utf-8"))
                self.memo[(m, cid)] = r
        return r


def cmd_post(a: argparse.Namespace) -> int:
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops20(ev, accts, priors)
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()
    m = METHOD

    def value_fn(sid: str):
        def f(squads):
            futs = {sq: pool.submit(ops.get, m, sid, sq) for sq in squads}
            return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}
        return f

    with ev:
        for sid in scs:
            out_path = LOG / f"plans_{sid}.jsonl"
            done = set()
            if out_path.exists():
                done = {json.loads(x)["plan"] for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()}
            acct = accts[sid]
            books = {run: load_book(sid, run) for _, run in PLANS}
            sq_all = [sq for b in books.values() for _, sq in b.values()]
            lsq = leaders_of(acct, ev, sq_all)
            for key, run in PLANS:
                if key in done:
                    continue
                best = books[run]
                leader = {c: lsq.get(sq) for c, (_, sq) in best.items()}
                r = policy_pf(best, value_fn(sid))
                post = r.pop("post")
                decks = [(v, tuple(sq)) for v, sq in r["decks"]]
                summ = load_summary(sid, run)
                rec = {"scenario": sid, "plan": key, "run": run, "account_evals": summ["evals"],
                       "post_comps": len(r["ran"]), "post_evals": len(r["ran"]) * R18.BUDGET["T"],
                       "total": r["total"], "decks": r["decks"], "rounds": r["rounds"],
                       "leaders": [leader.get(frozenset(sq)) for _, sq in decks],
                       "settings": {">".join(sq): (ops.get_cached(m, R17.comp_id(sid, sq)) or {}).get("labels")
                                    for _, sq in decks}}
                if key in ALT_PLANS:
                    lead_best = rec["leaders"]
                    ar = policy_pf(best, value_fn(sid), post=dict(post),
                                   packer=lambda p: leader_alt(best, p, lead_best, leader))
                    adecks = [(v, tuple(sq)) for v, sq in ar["decks"]]
                    pair = ar["extra"][0] if ar["extra"] else None
                    names_b = {n for _, sq in decks for n in sq}
                    rec["alt"] = {"total": ar["total"], "decks": ar["decks"], "pair": list(pair) if pair else None,
                                  "leaders": [leader.get(frozenset(sq)) for _, sq in adecks],
                                  "post_comps": len(ar["ran"]), "post_evals": len(ar["ran"]) * R18.BUDGET["T"],
                                  "rounds": ar["rounds"], "ratio": ar["total"] / r["total"] if r["total"] else None,
                                  "shared_nikkes": len(names_b & {n for _, sq in adecks for n in sq}),
                                  "best_after_alt": R18.pack(best, ar["post"])[0]}
                rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(json.dumps({k: rec[k] for k in ("scenario", "plan", "total")} |
                                 ({"alt": round(rec["alt"]["ratio"], 4)} if "alt" in rec else {}), ensure_ascii=False),
                      file=sys.stderr, flush=True)
        pool.shutdown()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "post", "only": a.only, "sims": ev.sim_count,
               "cache_hits": ev.cache_hits, "ran": dict(ops.ran), "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    log_run(rec)
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


def cmd_alt2(a: argparse.Namespace) -> int:
    """다듬은 유력 대안(rebuild_alt)을 한 판(--plan)의 최선 5덱에 대해 만들고 같은 후처리를 돌린다 → run_log/alt2_<계정>.jsonl."""
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    run = dict(PLANS)[a.plan]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops20(ev, accts, priors)
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()
    m = METHOD

    def value_fn(sid: str):
        def f(squads):
            futs = {sq: pool.submit(ops.get, m, sid, sq) for sq in squads}
            return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}
        return f

    with ev:
        for sid in scs:
            out_path = LOG / f"alt2_{sid}.jsonl"
            if out_path.exists() and any(json.loads(x)["plan"] == a.plan for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()):
                continue
            acct = accts[sid]
            best = load_book(sid, run)
            lsq = leaders_of(acct, ev, [sq for _, sq in best.values()])
            leader = {c: lsq.get(sq) for c, (_, sq) in best.items()}
            r = policy_pf(best, value_fn(sid))          # 판의 최선(운용 탐색은 기록에서 — 새 시뮬 없음)
            post = r.pop("post")
            bdecks = [tuple(sq) for _, sq in r["decks"]]
            ar = policy_pf(best, value_fn(sid), post=dict(post), packer=lambda p: rebuild_alt(best, p, bdecks, leader))
            adecks = [tuple(sq) for _, sq in ar["decks"]]
            rec = {"scenario": sid, "plan": a.plan, "total": r["total"], "alt_total": ar["total"],
                   "ratio": ar["total"] / r["total"] if r["total"] else None, "decks": r["decks"], "alt_decks": ar["decks"],
                   "pair": list(ar["extra"][0]) if ar["extra"] and ar["extra"][0] else None,
                   "leaders": [leader.get(frozenset(sq)) for sq in bdecks],
                   "alt_leaders": [leader.get(frozenset(sq)) for sq in adecks],
                   "post_comps": len(ar["ran"]), "post_evals": len(ar["ran"]) * R18.BUDGET["T"],
                   "best_after_alt": R18.pack(best, ar["post"])[0], **alt_shape(bdecks, adecks, leader),
                   "settings": {">".join(sq): (ops.get_cached(m, R17.comp_id(sid, sq)) or {}).get("labels") for sq in adecks},
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps({k: rec[k] for k in ("scenario", "plan", "total", "alt_total", "rebuilt", "new_leaders")},
                             ensure_ascii=False), file=sys.stderr, flush=True)
        pool.shutdown()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "alt2", "plan": a.plan, "only": a.only, "sims": ev.sim_count,
               "cache_hits": ev.cache_hits, "ran": dict(ops.ran), "seconds": round(time.time() - t0)}
    log_run(rec)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("--only")
    p.add_argument("--runs", help="고를 계정 탐색(예: U4_4000,CL_3000)")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("post")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.set_defaults(func=cmd_post)
    p = sub.add_parser("alt2")
    p.add_argument("--plan", required=True, choices=[k for k, _ in PLANS])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.set_defaults(func=cmd_alt2)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
