"""실험 42 — 규칙 없는 묶음 단위 탐색. README.

    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py free --season 36       # 0a 규칙 없는 표(끊기면 같은 명령)
    python -I experiments/42_bundle_search/run42.py freepack --season 36                                    # 0b 규칙 없는 OPT(시뮬 0)
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py ordercheck --season 36  # 0c 단계 안 순서 × 카메라
    python -I experiments/42_bundle_search/run42.py replay --season 36 --arm P --seed 0                     # 1단계(시뮬 0)

- 값 · 계정 · 풀은 실험 41과 같다(`run41.options` · `pool41.json`, 기본 순서 `run41.base_order`). 바꾸는 것은 공간(5인 조합 전부)이다.
- 0a 표는 실험 41 표(규칙 공간)의 같은 구성을 그대로 다시 쓴다 — 같은 요청(같은 순서 · options · 평가기)이라 값이 같다.
- 실행 중 기록은 `NIKKE42_LOG`(레포 밖 작업 폴더)에 쓸 수 있다. 없으면 이 폴더의 `run_log/`.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import sys
import time
from itertools import combinations
from math import comb
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R41 = sys.modules.get("run41") or _load("run41", EXPS / "41_ground_truth" / "run41.py")
P41, run31, R10, R9 = R41.P41, R41.run31, R41.R10, R41.R9
E8 = 1e8

SEASONS = R41.SEASONS
CHUNK = 5000
LOG = Path(os.environ.get("NIKKE42_LOG") or HERE / "run_log")
BURST = R41.BURST


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


jload, jdump, pool, options, base_order = R41.jload, R41.jdump, R41.pool, R41.options, R41.base_order


# ---------------------------------------------------------------- 0a 규칙 없는 표

def free_comps(s: int) -> list[tuple[str, ...]]:
    """풀의 5인 조합 전부(이름순 조합 순서 — 원소도 이름순 튜플, 실험 41 구성과 같은 모양)."""
    return list(combinations(sorted(pool(s)), 5))


def free_count(s: int) -> int:
    return comb(len(pool(s)), 5)


def chunk_file(s: int, k: int) -> Path:
    return sdir(s) / "free" / f"c{k:04d}.jsonl.gz"


def exp41_rows(s: int) -> dict[tuple, tuple[float | None, list | None]]:
    """실험 41 표(레포 기록) — 구성 → (값, 니케별 딜)."""
    cs = R41.comps(s)
    out: dict[tuple, tuple[float | None, list | None]] = {}
    for i, v, m in R41.iter_table(s):
        out[cs[i]] = (v, m)
    return out


def iter_free(s: int) -> Iterator[list]:
    for f in sorted((sdir(s) / "free").glob("c*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)


def load_free(s: int) -> tuple[list[tuple[str, ...]], list[float | None]]:
    cs = free_comps(s)
    vals: list[float | None] = [None] * len(cs)
    for r in iter_free(s):
        vals[r[0]] = r[1]
    return cs, vals


def free_table(s: int) -> Any:
    """규칙 없는 표를 실험 41 `Table`로(기본 순서 값만)."""
    cs, vals = load_free(s)
    miss = sum(v is None for v in vals)
    if miss:
        meta = jload(sdir(s) / "free_meta.json") or {}
        errs = sum(p.get("errors", 0) for p in meta.get("parts", {}).values())
        if miss > errs:
            raise RuntimeError(f"S{s} 규칙 없는 표가 덜 됐다: 값 없는 구성 {miss:,} (오류 {errs})")
    return R41.Table(s, cs, vals, None, pool(s))


def cmd_free(a: argparse.Namespace) -> int:
    s = a.season
    cs = free_comps(s)
    n_chunks = (len(cs) + CHUNK - 1) // CHUNK
    meta_f = sdir(s) / "free_meta.json"
    meta = jload(meta_f) or {"season": s, "comps": len(cs), "chunk": CHUNK, "chunks": n_chunks, "options": options(s),
                             "order": "실험 41 base_order(단계 1 · 2 · A · 3, 같은 단계 안 이름순)", "parts": {}}
    old = exp41_rows(s)
    with R41.evaluator(a.jobs) as ev:
        ver = R41.ev_version(ev)
        for k in range(n_chunks):
            f = chunk_file(s, k)
            if f.exists():
                continue
            if a.limit is not None and a.limit <= 0:
                break
            idx = list(range(k * CHUNK, min((k + 1) * CHUNK, len(cs))))
            new = [i for i in idx if cs[i] not in old]
            t0, n0 = time.time(), ev.sim_count
            got = dict(zip(new, R41.run_orders(s, [base_order(cs[i]) for i in new], ev))) if new else {}
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                for i in idx:
                    if i in got:
                        v, m = got[i]
                        fh.write(json.dumps([i, v, m, 0], ensure_ascii=False) + "\n")
                    else:
                        v, m = old[cs[i]]
                        fh.write(json.dumps([i, v, m, 41], ensure_ascii=False) + "\n")
            tmp.rename(f)
            sec = time.time() - t0
            meta["parts"][str(k)] = {"sims": ev.sim_count - n0, "reused": len(idx) - len(new), "seconds": round(sec, 1),
                                     "errors": sum(got[i][0] is None for i in got), "evaluator": ver}
            jdump(meta_f, meta)
            print(f"S{s} 조각 {k + 1}/{n_chunks} ({len(meta['parts'])} 끝) 새 {len(new)} · 재사용 {len(idx) - len(new)} "
                  f"{sec:.0f}초 {(ev.sim_count - n0) / max(sec, 1e-9):.1f}/초", flush=True)
            if a.limit is not None:
                a.limit -= 1
    return 0


# ---------------------------------------------------------------- 0c 순서 확인: 단계 안 순서 × 카메라 대 120순서

def with_camera(s: int, name: str) -> dict[str, Any]:
    o = options(s)
    o["operation"] = {**o.get("operation", {}), "camera": name}
    return o


def order_targets(s: int) -> dict[int, dict[tuple, float]]:
    """실험 41 자리 순서 대상 중 120순서를 모두 잰 구성 → {순서: 값}(카메라 기본)."""
    T = R41.Table.load(s)
    P = R41.load_perm(s)
    out = {}
    for i, d in P.items():
        allv = dict(d)
        for v, o in T.refined.get(i, {}).values():
            allv[tuple(o)] = v
        allv[base_order(T.cs[i])] = T.base[i]
        if len(allv) == 120:
            out[i] = allv
    return out


def cmd_ordercheck(a: argparse.Namespace) -> int:
    from nikke_opt.evaluator import EvalRequest
    s = a.season
    f = sdir(s) / "ordercheck.jsonl.gz"
    if f.exists():
        return 0
    T = R41.Table.load(s)
    tg = order_targets(s)
    jobs = []
    for i in sorted(tg):
        for o in R41.R2.distinct_orders(base_order(T.cs[i]), BURST):
            for n in o:
                jobs.append((i, tuple(o), n))
    t0 = time.time()
    with R41.evaluator(a.jobs) as ev:
        res = ev.evaluate([EvalRequest(o, boss=None, options=with_camera(s, n)) for _, o, n in jobs])
        tmp = f.with_suffix(".tmp")
        f.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            for (i, o, n), r in zip(jobs, res):
                v = None if r.error or r.total_damage is None else r.total_damage / E8
                fh.write(json.dumps({"i": i, "order": list(o), "camera": n, "value": v}, ensure_ascii=False) + "\n")
        tmp.rename(f)
        jdump(sdir(s) / "ordercheck_meta.json", {"season": s, "comps": len(tg), "requests": len(jobs), "sims": ev.sim_count,
                                                 "seconds": round(time.time() - t0, 1), "evaluator": R41.ev_version(ev)})
    summ = order_summary(s)
    jdump(sdir(s) / "ordercheck_summary.json", summ)
    print(json.dumps({k: v for k, v in summ.items() if k != "short"}, ensure_ascii=False), flush=True)
    return 0


def order_summary(s: int) -> dict[str, Any]:
    """(1) 카메라를 3번 자리 니케로 적은 값 = 적지 않은 값인가, (2) 커버율 = max(단계 안 순서 × 카메라) ÷ max(120순서) —
    전부 보기와, 싼 차례(기본 카메라로 단계 안 순서 최선 → 그 순서에서 카메라 5명)."""
    tg = order_targets(s)
    rows: dict[int, list] = {}
    with gzip.open(sdir(s) / "ordercheck.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows.setdefault(r["i"], []).append(r)
    same, diff, cover, cheap, gain_cam = 0, [], [], [], []
    for i, rs in rows.items():
        allv = tg[i]
        best120 = max(allv.values())
        for r in rs:
            o = tuple(r["order"])
            if r["camera"] == o[2] and r["value"] is not None:
                if abs(r["value"] - allv[o]) <= 1e-6:
                    same += 1
                else:
                    diff.append([i, r["order"], r["value"], allv[o]])
        full = max(r["value"] for r in rs if r["value"] is not None)
        cover.append(full / best120)
        reps = {tuple(r["order"]) for r in rs}
        o_best = max(reps, key=lambda o: allv[o])
        c_best = max([allv[o_best]] + [r["value"] for r in rs if tuple(r["order"]) == o_best and r["value"] is not None])
        cheap.append(c_best / best120)
        gain_cam.append(c_best / allv[o_best] - 1)
    q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))]  # noqa: E731
    short = []
    for i, rs in rows.items():
        allv = tg[i]
        o120, v120 = max(allv.items(), key=lambda kv: kv[1])
        b = max((r for r in rs if r["value"] is not None), key=lambda r: r["value"])
        if b["value"] / v120 < 0.99:
            short.append({"i": i, "cover": b["value"] / v120, "best120": list(o120), "v120": v120,
                          "best": b["order"], "camera": b["camera"], "v": b["value"]})
    return {"season": s, "comps": len(rows), "short": sorted(short, key=lambda x: x["cover"]), "camera_slot3_same": same, "camera_slot3_diff": len(diff), "diff_examples": diff[:5],
            "cover_full": {"median": R41.median(cover), "p10": q(cover, 0.1), "min": min(cover), "ge_99": sum(x >= 0.99 for x in cover)},
            "cover_cheap": {"median": R41.median(cheap), "p10": q(cheap, 0.1), "min": min(cheap), "ge_99": sum(x >= 0.99 for x in cheap)},
            "camera_gain_on_best_order": {"median": R41.median(gain_cam), "max": max(gain_cam)}}


# ---------------------------------------------------------------- 0b 규칙 없는 OPT(시뮬 0)

def cmd_freepack(a: argparse.Namespace) -> int:
    s = a.season
    T = free_table(s)
    t0 = time.time()
    opt = R41.exact_opt(T, "base", deadline_s=a.deadline)
    rk = T.ranks("base")
    opt["ranks"] = [rk[i] for i in opt["idx"]]
    opt["outside_rule"] = [list(T.cs[i]) for i in opt["idx"] if not P41.passes(T.cs[i])]
    land = {}
    for x in R41.LAND_X:
        L = R41.landscape(T, "base", opt["total"], x, cap=a.cap, deadline_s=a.deadline)
        land[str(x)] = {k: L[k] for k in ("candidates", "count", "complete", "stop")} | {
            "comps_in": len(L["comps_in"]), "outside_rule_in": sum(not P41.passes(T.cs[i]) for i in L["comps_in"])}
        if x == min(R41.LAND_X):
            low_keep = L["keep"]
    cm = R41.R30.class_map(T.book("base", low_keep), max_reps=R41.CLASS_MAX, low=R41.CLASS_LOW)
    classes = {str(x): sum(1 for r in cm["reps"] if not r.get("below") and r["total"] >= x * opt["total"] - 1e-9) for x in R41.LAND_X}
    rn = {str(x): R41.r_need(T, "base", x * opt["total"], deadline_s=a.deadline) for x in R41.RNEED_X}
    rule = R41.jload(R41.sdir(s) / "pack.json")["base"]["opt"]
    out = {"season": s, "comps": len(T.cs), "opt": opt, "rule_opt_base": rule["total"], "gain_vs_rule": opt["total"] / rule["total"] - 1,
           "landscape": land, "classes": classes, "class_reps": cm["reps"], "r_need": rn, "seconds": round(time.time() - t0, 1)}
    jdump(sdir(s) / "freepack.json", out)
    print(json.dumps({"season": s, "opt": opt["total"], "exact": opt["exact"], "rule_opt": rule["total"],
                      "gain": out["gain_vs_rule"], "ranks": opt["ranks"], "outside_rule": opt["outside_rule"],
                      "land": {k: (v["count"], v["complete"], v["outside_rule_in"]) for k, v in land.items()},
                      "classes": classes, "r_need": {k: v["K"] for k, v in rn.items()}}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 1단계 재생(기본 값 세계, 시뮬 0)

REPLAY_SEEDS = (0, 1, 2, 3)
REPLAY_BUDGET = run31.SEED_BUDGET    # 12,500


class BaseWorldEvaluator:
    """표를 보는 평가기 — 요청 구성의 기본 순서 값으로 답한다(순서는 값에 안 들어감). 표 밖 구성은 KeyError."""

    def __init__(self, T: Any):
        from nikke_opt.evaluator import EvalResult
        self.T, self._R = T, EvalResult
        self.sim_count, self.cache_hits = 0, 0
        self.version = {"repo": "table42", "commit": f"S{T.s}"}
        self.outside_rule = 0

    def evaluate(self, requests: Sequence[Any]) -> list[Any]:
        out = []
        for r in requests:
            i = self.T.idx[frozenset(r.squad)]
            v = self.T.base[i]
            self.sim_count += 1
            self.outside_rule += not P41.passes(self.T.cs[i])
            raw = {"total_damage": None, "error": {"message": "표 값 없음"}} if v is None else {"total_damage": round(v * E8)}
            out.append(self._R(None if v is None else round(v * E8), raw, False))
        return out

    def submit(self, requests: Sequence[Any]) -> list[Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def arms_mod() -> Any:
    return sys.modules.get("arms42") or _load("arms42", HERE / "arms.py")


def run_arm(acct: Any, arm: str, budget: int, ev: Any) -> tuple[dict, list, Any]:
    A = arms_mod()
    with A.patched(arm):
        return R10.run_method(acct, "G+E", budget, ev, pool=177)


def cmd_replay(a: argparse.Namespace) -> int:
    s = a.season
    T = free_table(s)
    fp = jload(sdir(s) / "freepack.json")
    if not fp:
        raise RuntimeError(f"S{s}: 먼저 freepack")
    opt = fp["opt"]["total"]
    rule_opt = fp["rule_opt_base"]
    seeds = REPLAY_SEEDS if a.seed is None else (a.seed,)
    tag = a.tag or a.arm
    for k in seeds:
        f = sdir(s) / "replay" / f"{tag}_s{k}.json"
        if f.exists() and not a.force:
            continue
        ev = BaseWorldEvaluator(T)
        acct = R41.replay_account(s, k)
        t0 = time.time()
        summ, recs, sess = run_arm(acct, a.arm, a.budget, ev)
        hist = summ["history"]
        fin = summ["final"]
        out = {"season": s, "arm": a.arm, "tag": tag, "params": dict(arms_mod().PARAMS) if a.arm != "base" else {},
               "seed": k, "account": acct.id, "budget": a.budget, "evals": summ["evals"], "opt": opt, "rule_opt": rule_opt,
               "final": fin, "final_ratio": fin["total"] / opt, "final_ratio_rule": fin["total"] / rule_opt,
               "reach": {str(x): R41.first_reach(hist, opt, x) for x in (0.99, 0.97)},
               "grid": R41.grid_of(hist, opt, budget=a.budget), "history": hist, "kicks": summ["kicks"],
               "outside_rule_requests": ev.outside_rule, "final_outside_rule": sum(not P41.passes(sorted(q)) for _, q in fin["squads"]),
               "errors": summ["errors"], "comps_seen": len(sess.book.best), "seconds": round(time.time() - t0, 1)}
        jdump(f, out)
        print(json.dumps({k2: out[k2] for k2 in ("season", "tag", "seed", "evals", "final_ratio", "reach", "final_outside_rule", "seconds")},
                         ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 명령

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("free")
    f.add_argument("--season", type=int, required=True)
    f.add_argument("--jobs", type=int, default=4)
    f.add_argument("--limit", type=int, default=None)
    c = sub.add_parser("ordercheck")
    c.add_argument("--season", type=int, required=True)
    c.add_argument("--jobs", type=int, default=4)
    k = sub.add_parser("freepack")
    k.add_argument("--season", type=int, required=True)
    k.add_argument("--cap", type=int, default=2_000_000)
    k.add_argument("--deadline", type=float, default=900.0)
    y = sub.add_parser("replay")
    y.add_argument("--season", type=int, required=True)
    y.add_argument("--arm", required=True, choices=("base", "R", "P", "L"))
    y.add_argument("--seed", type=int, default=None)
    y.add_argument("--budget", type=int, default=REPLAY_BUDGET)
    y.add_argument("--tag", default=None, help="기록 이름(개발 중 판 수치를 바꿔 볼 때)")
    y.add_argument("--force", action="store_true")
    a = p.parse_args(argv)
    return {"free": cmd_free, "ordercheck": cmd_ordercheck, "freepack": cmd_freepack, "replay": cmd_replay}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
