"""실험 21 — 1차 목표 재검증: 새 검증 계정 u1~u8에서 실험 20이 고른 절차 (README §절차 · §판).

    source .cache/evaluators.env && python experiments/21_first_goal_recheck/run21.py search [--only u1] [--runs U4_4000]
        → run_log/accounts/<계정>_<탐색>.json · .jsonl.gz
    source .cache/evaluators.env && python experiments/21_first_goal_recheck/run21.py post [--only u1]
        → run_log/ops/<기법>/<해시>.json · run_log/plans_<계정>.jsonl

계정 탐색 · 후처리 · 주력 딜러 · 유력 대안은 실험 20 `run20`의 함수를 그대로 쓴다. 절차의 계정 탐색(P_RUN)은 실험 20 판단이다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

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


import accounts21 as A21  # noqa: E402

R20 = sys.modules.get("run20") or _load("run20", EXPS / "20_search_robust" / "run20.py")
AC, R19, R18, R17, R10, R9 = R20.AC, R20.R19, R20.R18, R20.R17, R20.R10, R20.R9
E8 = R20.E8

P_RUN = "U4_3000"         # 실험 20 판단(계정 탐색 = C3 · U4 3,000) — 사전 등록 커밋
REF_RUN = "U4_4000"       # P_RUN이 U4_4000이면 참조는 U4_6000
RUNS = dict(R20.RUNS, U4_6000=("P", 6000))


def plans() -> tuple[tuple[str, str, str | None, str | None], ...]:
    """(기호, 계정 탐색, 정책, 기법). 정책 None = 후처리 없음."""
    ref = "U4_6000" if P_RUN == "U4_4000" else REF_RUN
    return (("B1", "U4_2000", "PS", "C"),          # 이 세션 전 기본: 틀별 상위 5 + 컨트롤만
            ("P0", "U4_2000", "PF", R20.METHOD),    # 실험 19 절차
            ("P", P_RUN, "PF", R20.METHOD),         # 보강한 절차(실험 20 판단) + 유력 대안
            ("B0w", "U4_4000", None, None),         # 운용 대신 조합 탐색에 예산 더(고정 운용)
            ("REF", ref, "PF", R20.METHOD))         # 참조: 큰 조합 예산 + 절차


def needed_runs() -> list[str]:
    return list(dict.fromkeys(p[1] for p in plans()))


def run_file(sid: str, run: str) -> Path:
    return LOG / "accounts" / f"{sid}_{run}"


def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in A21.check_scenarios() if not only or s["id"] in only.split(",")}


def log_run(rec) -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_search(a: argparse.Namespace) -> int:
    if P_RUN is None:
        raise SystemExit("P_RUN(실험 20 판단)이 비어 있다")
    scs = scenarios(a.only)
    runs = a.runs.split(",") if a.runs else needed_runs()
    out = LOG / "accounts"
    out.mkdir(parents=True, exist_ok=True)
    pre = json.loads(R19.PRE["U4"].read_text(encoding="utf-8"))
    R10.pack_alt20 = lambda *x, **k: (0.0, [])
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
                summ, recs = R20.run_two(acct, b, ev, pre)
            summ.update(run=run, scenario=sid)
            R10.write_run(out, f"{sid}_{run}", summ, recs)
            print(json.dumps({"run": f"{sid}_{run}", "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "search", "only": a.only, "runs": [f"{s}_{r}" for s, r in tasks],
               "sims": ev.sim_count, "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    log_run(rec)
    return 0


class Ops21(R19.Ops19):
    def __init__(self, ev, accts, priors):
        super().__init__(ev, accts, priors)
        self.out = LOG / "ops"


def cmd_post(a: argparse.Namespace) -> int:
    if P_RUN is None:
        raise SystemExit("P_RUN(실험 20 판단)이 비어 있다")
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops21(ev, accts, priors)
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()

    def value_fn(m: str, sid: str):
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
            books = {run: R9.book_of(R9.load_records(Path(f"{run_file(sid, run)}.jsonl.gz"))) for run in needed_runs()}
            lsq = R20.leaders_of(acct, ev, [sq for b in books.values() for _, sq in b.values()])
            for key, run, pol, m in plans():
                if key in done:
                    continue
                best = books[run]
                leader = {c: lsq.get(sq) for c, (_, sq) in best.items()}
                summ = json.loads(Path(f"{run_file(sid, run)}.json").read_text(encoding="utf-8"))
                if pol is None:
                    tot, dk = R18.pack(best, {})
                    r = {"total": tot, "decks": [[v, list(sq)] for v, sq in dk], "ran": [], "rounds": 0, "post": {}}
                elif pol == "PS":
                    rr = R18.run_policy("PS", best, value_fn(m, sid))
                    r = {"total": rr["total"], "decks": rr["decks"], "ran": [None] * rr["post"], "rounds": rr["rounds"], "post": {}}
                else:
                    r = R20.policy_pf(best, value_fn(m, sid))
                post = r.pop("post")
                decks = [(v, tuple(sq)) for v, sq in r["decks"]]
                rec = {"scenario": sid, "plan": key, "run": run, "policy": pol, "method": m,
                       "account_evals": summ["evals"], "post_comps": len(r["ran"]),
                       "post_evals": len(r["ran"]) * (R18.BUDGET[m.split("@")[0]] if m else 0),
                       "total": r["total"], "decks": r["decks"], "rounds": r["rounds"],
                       "leaders": [leader.get(frozenset(sq)) for _, sq in decks],
                       "settings": {">".join(sq): (ops.get_cached(m, R17.comp_id(sid, sq)) or {}).get("labels") if m else None
                                    for _, sq in decks}}
                if key == "P":
                    lead_best = rec["leaders"]
                    ar = R20.policy_pf(best, value_fn(m, sid), post=dict(post),
                                       packer=lambda p: R20.leader_alt(best, p, lead_best, leader))
                    adecks = [(v, tuple(sq)) for v, sq in ar["decks"]]
                    pair = ar["extra"][0] if ar["extra"] else None
                    names_b = {n for _, sq in decks for n in sq}
                    rec["alt"] = {"total": ar["total"], "decks": ar["decks"], "pair": list(pair) if pair else None,
                                  "leaders": [leader.get(frozenset(sq)) for _, sq in adecks],
                                  "post_comps": len(ar["ran"]), "post_evals": len(ar["ran"]) * R18.BUDGET["T"],
                                  "rounds": ar["rounds"], "ratio": ar["total"] / r["total"] if r["total"] else None,
                                  "shared_nikkes": len(names_b & {n for _, sq in adecks for n in sq}),
                                  "best_after_alt": R18.pack(best, ar["post"])[0],
                                  "settings": {">".join(sq): (ops.get_cached(m, R17.comp_id(sid, sq)) or {}).get("labels")
                                               for _, sq in adecks}}
                rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                with out_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        pool.shutdown()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "post", "only": a.only, "sims": ev.sim_count,
               "cache_hits": ev.cache_hits, "ran": dict(ops.ran), "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    log_run(rec)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("--only")
    p.add_argument("--runs")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("post")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.set_defaults(func=cmd_post)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
