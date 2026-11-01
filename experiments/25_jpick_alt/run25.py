"""실험 25 — J 상한 고르기 대안: 새 계정 w1~w8에서 실험 21 고정 절차(P) + 「최선과 J ≤ 0.3」 대안(후처리 포함).

    source .cache/evaluators.env && python experiments/25_jpick_alt/run25.py search [--only w1,w2]
        → run_log/accounts/<계정>_U4_3000.json · .jsonl.gz
    source .cache/evaluators.env && python experiments/25_jpick_alt/run25.py post [--only w1]
        → run_log/ops/<기법>/<해시>.json · run_log/plans_<계정>.jsonl
    python experiments/25_jpick_alt/run25.py analyze        → results.md · analysis.json(시뮬 없음)

- 최선: 실험 21 P 판 그대로 — 공유 사전 계산 U4 → 계정 탐색 3,000(`run10.run_method` P) → 5덱 고정점 후처리(JT 400, `run20.policy_pf`).
- 대안(θ): 같은 계정 기록에서, 후처리 뒤 최선 5덱과 쌍 자카드 J ≤ θ인 5덱 중 합 최대(값 = max(기본 레이어, 운용 값)).
  같은 고정점 후처리(`policy_pf`)를 J 상한 묶기로 돈다 — 실험 21 유력 대안의 묶기(`rebuild_alt`)만 바꾼 것이다.
  θ = 0.3(판정) · 0.2(관찰). 주력 딜러 개념은 쓰지 않는다.
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EXPS / "20_search_robust"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


import accounts25 as A25  # noqa: E402

R20 = sys.modules.get("run20") or _load("run20", EXPS / "20_search_robust" / "run20.py")
P24 = sys.modules.get("pick24") or _load("pick24", EXPS / "24_diverse_pick" / "pick24.py")
AC, R19, R18, R17, R10, R9 = R20.AC, R20.R19, R20.R18, R20.R17, R20.R10, R20.R9
SIM = P24.SIM
E8 = R20.E8

RUN, BUDGET = "U4_3000", 3000      # 실험 21 P 판의 계정 탐색
METHOD = R20.METHOD                # JT 400
THETAS = (0.3, 0.2)                # 0.3 = 판정(README §사전 등록), 0.2 = 관찰
MAIN_THETA = 0.3
ALT_RATIO = 0.97
PASS_COUNT = 6                     # 8개 중
PACK_LIMIT = 300.0                 # J 상한 묶기 제한 시간(초) — 넘으면 찾은 해를 쓰고 표시한다


def run_file(sid: str) -> Path:
    return LOG / "accounts" / f"{sid}_{RUN}"


def scenarios(only: str | None) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in A25.check_scenarios() if not only or s["id"] in only.split(",")}


def log_run(rec: Mapping[str, Any]) -> None:
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "run_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def cmd_search(a: argparse.Namespace) -> int:
    scs = scenarios(a.only)
    out = LOG / "accounts"
    out.mkdir(parents=True, exist_ok=True)
    pre = json.loads(R19.PRE["U4"].read_text(encoding="utf-8"))
    R10.pack_alt20 = lambda *x, **k: (0.0, [])   # 실험 11 · 13 · 19 · 21과 같다
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    done = []
    with ev:
        for sid, s in scs.items():
            if Path(f"{run_file(sid)}.json").exists():
                continue
            summ, recs, _ = R10.run_method(AC.AccountT(s), "P", BUDGET, ev, pre=pre, pool=177)
            summ.pop("alt20", None)
            summ.update(run=RUN, scenario=sid)
            R10.write_run(out, f"{sid}_{RUN}", summ, recs)
            done.append(sid)
            print(json.dumps({"run": f"{sid}_{RUN}", "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)
        log_run({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "search", "only": a.only, "runs": done,
                 "sims": ev.sim_count, "cache_hits": ev.cache_hits, "seconds": round(time.time() - t0),
                 "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"})
    return 0


def jpacker(best: Mapping[frozenset, tuple[float, tuple]], best_decks: Sequence[tuple], theta: float,
            flags: dict[str, Any]):
    """고정점 후처리에 넘기는 묶기: 최선 5덱(후처리 뒤)과 J ≤ θ인 겹치지 않는 5덱 중 max(기본, 운용 값) 합 최대."""
    bd = [frozenset(sq) for sq in best_decks]
    cost = P24.pair_cost(best, bd)
    budget = P24.budget_of(theta)

    def pk(post: Mapping[tuple, float]) -> tuple[float, list[tuple[float, tuple]]]:
        vals = {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in best.items()}
        try:
            return R9.pack_vals(vals, cost=cost, budget=budget, deadline=time.monotonic() + PACK_LIMIT)
        except R9.PackTimeout as e:
            flags["timeouts"] = flags.get("timeouts", 0) + 1
            return e.total, e.decks
    return pk


class Ops25(R19.Ops19):
    def __init__(self, ev, accts, priors):
        super().__init__(ev, accts, priors)
        self.out = LOG / "ops"


def cmd_post(a: argparse.Namespace) -> int:
    scs = scenarios(a.only)
    accts = {sid: AC.AccountT(s) for sid, s in scs.items()}
    priors = json.loads((R19.LOG / "priors.json").read_text(encoding="utf-8"))["priors"]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    ops = Ops25(ev, accts, priors)
    pool = ThreadPoolExecutor(max_workers=a.workers)
    t0 = time.time()

    def value_fn(sid: str):
        def f(squads):
            futs = {sq: pool.submit(ops.get, METHOD, sid, sq) for sq in squads}
            return {sq: fu.result()["value"] / E8 for sq, fu in futs.items()}
        return f

    def settings(sid: str, decks) -> dict[str, Any]:
        return {">".join(sq): (ops.get_cached(METHOD, R17.comp_id(sid, sq)) or {}).get("labels") for _, sq in decks}

    with ev:
        for sid in scs:
            out_path = LOG / f"plans_{sid}.jsonl"
            if out_path.exists():
                continue
            best = R9.book_of(R9.load_records(Path(f"{run_file(sid)}.jsonl.gz")))
            summ = json.loads(Path(f"{run_file(sid)}.json").read_text(encoding="utf-8"))
            sims0 = ev.sim_count
            r = R20.policy_pf(best, value_fn(sid))
            post = r.pop("post")
            decks = [(v, tuple(sq)) for v, sq in r["decks"]]
            bdecks = [sq for _, sq in decks]
            rec: dict[str, Any] = {"scenario": sid, "plan": "P", "run": RUN, "method": METHOD, "account_evals": summ["evals"],
                                   "post_comps": len(r["ran"]), "post_evals": len(r["ran"]) * R18.BUDGET["T"],
                                   "total": r["total"], "decks": r["decks"], "rounds": r["rounds"],
                                   "settings": settings(sid, decks), "sims_best": ev.sim_count - sims0, "alts": {}}
            for th in THETAS:
                flags: dict[str, Any] = {}
                s0 = ev.sim_count
                ar = R20.policy_pf(best, value_fn(sid), post=dict(post), packer=jpacker(best, bdecks, th, flags))
                adecks = [(v, tuple(sq)) for v, sq in ar["decks"]]
                rec["alts"][str(th)] = {
                    "total": ar["total"], "decks": ar["decks"], "ratio": ar["total"] / r["total"] if r["total"] else None,
                    **SIM.compare([list(sq) for sq in bdecks], [list(sq) for _, sq in adecks]),
                    "post_comps": len(ar["ran"]), "post_evals": len(ar["ran"]) * R18.BUDGET["T"], "rounds": ar["rounds"],
                    "best_after_alt": R18.pack(best, ar["post"])[0], "timeouts": flags.get("timeouts", 0),
                    "sims": ev.sim_count - s0, "settings": settings(sid, adecks)}
            rec["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps({"scenario": sid, "total": round(r["total"], 2),
                              "ratios": {k: round(v["ratio"] or 0, 4) for k, v in rec["alts"].items()},
                              "t": round(time.time() - t0), "sims": ev.sim_count}, ensure_ascii=False), flush=True)
        pool.shutdown()
        log_run({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cmd": "post", "only": a.only, "sims": ev.sim_count,
                 "cache_hits": ev.cache_hits, "ran": dict(ops.ran), "seconds": round(time.time() - t0),
                 "evaluator": f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"})
    return 0


# ---------------------------------------------------------------- 분석(README §판단 기준)

def verdict(ratios: Sequence[float | None]) -> str:
    ok = sum(1 for r in ratios if r is not None and r >= ALT_RATIO)
    return f"통과 ({ok}/{len(ratios)})" if ok >= PASS_COUNT else f"미통과 ({ok}/{len(ratios)})"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def cmd_analyze(a: argparse.Namespace) -> int:
    rows = []
    for sid in [s["id"] for s in A25.check_scenarios()]:
        p = LOG / f"plans_{sid}.jsonl"
        if p.exists():
            rows.append([json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()][-1])
    v = verdict([r["alts"][str(MAIN_THETA)]["ratio"] for r in rows]) if rows else "기록 없음"
    L = ["# 실험 25 결과 — J 상한 고르기 대안(새 계정 w1~w8)", "",
         "`python experiments/25_jpick_alt/run25.py analyze`가 만든다. 절차 · 기준은 [README](README.md).", "",
         f"**판단(사전 등록, θ = {MAIN_THETA}): {v}** — 대안 5덱 합(후처리 뒤) ≥ 최선의 {ALT_RATIO:.0%}인 계정이 {PASS_COUNT}개 이상이면 통과.", "",
         "| 계정 | 최선(억) | θ = 0.3: 값 비율 · J · 바꿀 · 공유 | θ = 0.2: 값 비율 · J · 바꿀 · 공유 | 대안 후처리로 최선이 오른 몫 | 새 시뮬(최선 · 대안 0.3 · 0.2) |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        cells = []
        for th in ("0.3", "0.2"):
            x = r["alts"][th]
            mark = " (시간 초과 있음)" if x.get("timeouts") else ""
            cells.append(f"{pct(x['ratio'])} · {x['pair_jaccard']:.2f} · {x['moves']} · {x['shared_nikkes']}{mark}")
        up = max(x["best_after_alt"] for x in r["alts"].values()) / r["total"] - 1
        L.append(f"| {r['scenario']} | {r['total']:.1f} | {cells[0]} | {cells[1]} | {up * 100:+.2f}% | "
                 f"{r['sims_best']} · {r['alts']['0.3']['sims']} · {r['alts']['0.2']['sims']} |")
    for th in ("0.3", "0.2"):
        rs = [r["alts"][th]["ratio"] for r in rows]
        if rs:
            L.append(f"\nθ = {th}: 값 비율 중앙 {pct(statistics.median(rs))} · 최소 {pct(min(rs))} · 97% 이상 {sum(x >= ALT_RATIO for x in rs)}/{len(rs)} · "
                     f"J 중앙 {statistics.median([r['alts'][th]['pair_jaccard'] for r in rows]):.2f}.")
    L.append("")
    (HERE / "results.md").write_text("\n".join(L), encoding="utf-8")
    (HERE / "analysis.json").write_text(json.dumps({"verdict": v, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(v)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("--only")
    p.set_defaults(func=cmd_search)
    p = sub.add_parser("post")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--only")
    p.set_defaults(func=cmd_post)
    p = sub.add_parser("analyze")
    p.set_defaults(func=cmd_analyze)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
