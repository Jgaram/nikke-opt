"""실험 19 — 1차 목표 검증: 개발에 쓰지 않은 계정에서 고정한 전체 절차 실행기 (README §절차 · §판 · §예산과 실행).

    source .cache/evaluators.env && python experiments/19_first_goal/run19.py search [--workers 4] [--only t1]
        → run_log/accounts/<계정>_<사전 계산>_<예산>.json · .jsonl.gz(계정 탐색, 실험 10 형식)
    python experiments/19_first_goal/run19.py prior          → run_log/priors.json(배포 사전값: 개발 v1~v8 J 기록 전부)
    source .cache/evaluators.env && python experiments/19_first_goal/run19.py post [--workers 6]
        → run_log/ops/<기법>/<해시>.json(구성마다 운용 탐색) · run_log/plans.jsonl(계정 × 판 결과)

- 계정: accounts.py t1~t8(고정 시드). 조합 · 배치 탐색 = 실험 13 U4 흐름(L0, 공유 사전 계산 PB15 시드 4개 합치기) 그대로.
- 신캐 모사: 실험 15 C3의 새 니케 3명(혼자 강한 신캐)을 「막 출시된 니케」로 둔다 — 운용 사전값에서 그 니케 기록을 지운다(큐브 전부 탐색).
  갱신 절차: F4(처음부터 다시 = U4) — 실험 15 기본, I1(새 시드 하나 이어 붙이기) — 실험 15 「혼자 강한 신캐」 규칙.
- 운용 탐색 · 후처리 정책은 실험 17 · 18 판단(README §절차)을 run18의 정책 · 기법으로 그대로 쓴다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

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


import accounts as AC  # noqa: E402

R17 = AC.R17
R18 = sys.modules.get("run18") or _load("run18", EXPS / "18_deck_post" / "run18.py")
R10, R9, M, CB = R17.R10, R17.R9, R17.M, R17.CB
E8 = R17.R16.E8

PRE = {"U4": EXPS / "13_seed_merge" / "run_log" / "precompute_U4.json",
       "I1": EXPS / "15_new_nikke" / "cases" / "C3" / "run_log" / "precompute_I1.json"}
NEW_NIKKES = tuple(json.loads((EXPS / "15_new_nikke" / "cases" / "C3" / "run_log" / "meta.json")
                              .read_text(encoding="utf-8"))["removed"])
NEW_CUBE = "택티컬 베어 큐브"   # 새 큐브 모사: 실험 17에서 렐릭 베어 다음으로 많이 고른 큐브
ACCOUNT_RUNS = (("U4", 2000), ("U4", 4000), ("I1", 2000))

# 판(plan) = (기호, 계정 탐색, 정책, 기법, 사전값). 정책 · 기법 None = 후처리 없음.
# P_POLICY · P_METHOD는 실험 18 판단으로 정한다(README §절차).
P_POLICY, P_METHOD = "PF", "T"
PLANS = (
    ("B0", ("U4", 2000), None, None, None),            # 고정 운용(출발 큐브 + 기본 레이어)
    ("B1", ("U4", 2000), "PS", "C", None),             # 이 세션 전 기본: 틀별 상위 5 + 컨트롤만
    ("B2", ("U4", 2000), P_POLICY, "C", None),          # 새 정책 + 컨트롤만(큐브 몫 분리)
    ("P", ("U4", 2000), P_POLICY, P_METHOD, "main"),   # 1차 절차
    ("B0w", ("U4", 4000), None, None, None),           # 운용 대신 조합 탐색에 예산 더(고정 운용)
    ("REF", ("U4", 4000), P_POLICY, P_METHOD, "main"),  # 참조: 큰 조합 예산 + 절차
    ("PI1", ("I1", 2000), P_POLICY, P_METHOD, "main"),  # 신캐 뒤 싼 갱신(I1) + 절차
    ("PNC", ("U4", 2000), P_POLICY, P_METHOD, "newcube"),  # 새 큐브 모사: 사전값에 NEW_CUBE 관찰 없음
)


def run_name(sid: str, pre: str, budget: int) -> str:
    return f"{sid}_{pre}_{budget}"


# ---------------------------------------------------------------- 계정 탐색

def cmd_search(a: argparse.Namespace) -> int:
    scs = [s for s in AC.test_scenarios() if not a.only or s["id"] in a.only.split(",")]
    out = LOG / "accounts"
    out.mkdir(parents=True, exist_ok=True)
    pres = {k: json.loads(p.read_text(encoding="utf-8")) for k, p in PRE.items()}
    R10.pack_alt20 = lambda *x, **k: (0.0, [])   # 실험 11 · 13과 같다(대안 (b) 계산 안 함)
    tasks = [(s, pre, b) for (pre, b) in sorted(ACCOUNT_RUNS, key=lambda t: -t[1]) for s in scs
             if not (out / f"{run_name(s['id'], pre, b)}.json").exists()
             and (not a.runs or f"{pre}_{b}" in a.runs.split(","))]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, pre, b = task
        acct = AC.AccountT(s)
        summ, recs, _ = R10.run_method(acct, "P", b, ev, pre=pres[pre], pool=177)
        summ.update(method=f"P:{pre}", scenario=s["id"], pre=pre, budget=b)
        summ.pop("alt20", None)
        name = run_name(s["id"], pre, b)
        R10.write_run(out, name, summ, recs)
        with lock:
            print(json.dumps({"run": name, "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for f in [pool.submit(work, t) for t in tasks]:
                f.result()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "search", "runs": len(tasks), "sims": ev.sim_count,
               "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


def load_book(sid: str, pre: str, budget: int) -> dict[frozenset, tuple[float, tuple]]:
    return R9.book_of(R9.load_records(LOG / "accounts" / f"{run_name(sid, pre, budget)}.jsonl.gz"))


# ---------------------------------------------------------------- 배포 사전값

def dev_deltas() -> dict[str, dict[tuple[str, str], list[float]]]:
    """실험 17 J 기록(개발 v1~v8 전부)의 (니케, 큐브) → log 딜 비."""
    t17 = json.loads((R17.LOG / "targets.json").read_text(encoding="utf-8"))
    by: dict[str, dict[tuple[str, str], list[float]]] = {}
    for sid, d in t17["scenarios"].items():
        acc: dict[tuple[str, str], list[float]] = defaultdict(list)
        for c in d["comps"]:
            for k, xs in R17.cube_deltas(R17.read_log(R17.LOG / "logs" / "J" / f"{R17.hname(c['id'])}.jsonl.gz")).items():
                acc[k].extend(xs)
        by[sid] = acc
    return by


def build_priors(by: Mapping[str, Mapping[tuple[str, str], list[float]]]) -> dict[str, dict[str, list[str]]]:
    """main: 새 니케(NEW_NIKKES) 기록을 지운 배포 사전값. newcube: 거기서 NEW_CUBE 관찰도 지운 판."""
    def strip(drop_cube: str | None):
        return {s: {k: v for k, v in d.items() if k[0] not in NEW_NIKKES and k[1] != drop_cube} for s, d in by.items()}
    return {"main": R17.build_prior(strip(None), held=""), "newcube": R17.build_prior(strip(NEW_CUBE), held="")}


def cmd_prior(a: argparse.Namespace) -> int:
    pri = build_priors(dev_deltas())
    out = {"source": "실험 17 J 기록(v1~v8 전부)", "new_nikkes": list(NEW_NIKKES), "new_cube": NEW_CUBE,
           "top_k": R17.TOP_K, "priors": pri}
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "priors.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print({k: len(v) for k, v in pri.items()})
    return 0


# ---------------------------------------------------------------- 운용 탐색(계정마다 큐브 보유 · 출발 큐브 · 사전값)

class Ops19(R18.Ops):
    """run18 Ops와 같되 계정마다 큐브 보유 · 출발 큐브를 쓰고, 기록 재사용 없이 이 실험 안에서만 나눠 쓴다.
    T의 사전값은 판마다 다를 수 있어(main · newcube) 기법 이름에 붙인다: T@main · T@newcube."""

    def __init__(self, ev: Any, accts: Mapping[str, Any], priors: Mapping[str, Mapping[str, list[str]]]):
        super().__init__(ev, accts, {}, out=LOG / "ops", reuse=False)
        self.pri = priors
        self.ran, self.reused = defaultdict(int), defaultdict(int)

    def run(self, m: str, sid: str, cid: str, squad: Sequence[str]) -> dict[str, Any]:
        acct = self.accts[sid]
        base, _, tag = m.partition("@")
        job = {"id": cid, "squad": list(squad)}
        logdir = self.out / "logs"
        inv, start = acct.cubes, acct.start
        if base == "C":
            sp = M.Space(list(squad), base=acct.options)
            run = M.Run(job, sp, self.ev, method="M3:k2", budget=R18.BUDGET["C"], out=None)
            R17.m3_from(run, sp.empty(), seed=M.job_seed(cid, "M3:k2"))
            r = {"value": run.best, "labels": list(sp.labels(run.best_sel)), "evals": run.used, "source": "run"}
        elif base in ("J", "T"):
            kw = {"allowed": self.pri[tag or "main"]} if base == "T" else {}
            res = R17.run_method("J" if base == "J" else "JT", job, acct, self.ev, inv, logdir=logdir / m, start=start, **kw)
            r = {"value": res["best_damage"], "labels": res["best_variants"], "evals": res["evals"], "source": "run"}
        elif base == "S":
            c = self.get("C", sid, squad)
            res = R17.run_method("SQ", job, acct, self.ev, inv, logdir=logdir / m, start_labels=c["labels"], start=start)
            v, lab = res["best_damage"], res["best_variants"]
            if v is None or c["value"] > v:
                v, lab = c["value"], c["labels"]
            r = {"value": v, "labels": lab, "evals": R18.BUDGET["S"], "source": "run"}
        else:
            raise ValueError(m)
        p = self.path(m, cid)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({**r, "id": cid, "squad": list(squad)}, ensure_ascii=False) + "\n", encoding="utf-8")
        return r


def plan_method(method: str | None, prior: str | None) -> str | None:
    if method is None:
        return None
    return f"{method}@{prior}" if method == "T" else method


def cmd_post(a: argparse.Namespace) -> int:
    scs = {s["id"]: s for s in AC.test_scenarios() if not a.only or s["id"] in a.only.split(",")}
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    books = {(sid, pre, b): load_book(sid, pre, b) for sid in scs for (pre, b) in ACCOUNT_RUNS}
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops19(ev, accts, priors)
    # 계정 묶음마다 프로세스 하나로 돌린다(5덱 조립 · 대리 모델이 Python이라 한 프로세스의 스레드로는 코어 하나만 쓴다)
    out_path = LOG / (f"plans_{a.only.replace(',', '-')}.jsonl" if a.only else "plans.jsonl")
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["scenario"], r["plan"]))
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0, lock = time.time(), threading.Lock()

    def value_fn(m: str, sid: str):
        def f(squads):
            futs = {sq: pool.submit(ops.get, m, sid, sq) for sq in squads}
            return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}
        return f

    def one(sid: str, plan: tuple) -> None:
        key, run, pol, meth, prior = plan
        if (sid, key) in done:
            return
        book = books[(sid, *run)]
        m = plan_method(meth, prior)
        if pol is None:
            tot, decks = R18.pack(book, {})
            r = {"total": tot, "decks": [[v, list(sq)] for v, sq in decks], "post": 0, "rounds": 0}
        else:
            r = R18.run_policy(pol, book, value_fn(m, sid))
        # 5덱 각 덱의 운용 설정(찾은 덱만): label 목록
        r["settings"] = {">".join(sq): (ops.get_cached(m, R17.comp_id(sid, sq)) or {}).get("labels") if m else None
                         for _, sq in r["decks"]}
        summ = json.loads((LOG / "accounts" / f"{run_name(sid, *run)}.json").read_text(encoding="utf-8"))
        rec = {"scenario": sid, "plan": key, "account_run": run_name(sid, *run), "policy": pol, "method": m,
               "account_evals": summ["evals"], "post_evals": r["post"] * (R18.BUDGET[meth] if meth else 0), **r,
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with lock:
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps({k: rec[k] for k in ("scenario", "plan", "total", "post", "rounds")}, ensure_ascii=False),
                  file=sys.stderr, flush=True)

    with ev:
        outer = ThreadPoolExecutor(max_workers=len(scs) * len(PLANS))
        for f in [outer.submit(one, sid, p) for sid in scs for p in PLANS]:
            f.result()
        outer.shutdown()
        pool.shutdown()
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "post", "sims": ev.sim_count, "cache_hits": ev.cache_hits,
               "ran": ops.ran, "seconds": round(time.time() - t0),
               "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"}
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.add_argument("--runs", help="계정 탐색 판만 고른다(예: U4_4000,I1_2000) — 한 계정의 판을 프로세스 여럿에 나눌 때")
    p.set_defaults(func=cmd_search)
    sub.add_parser("prior").set_defaults(func=cmd_prior)
    p = sub.add_parser("post")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--only")
    p.set_defaults(func=cmd_post)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
