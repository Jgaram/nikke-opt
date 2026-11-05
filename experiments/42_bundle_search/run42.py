"""실험 42 — 규칙 없는 묶음 단위 탐색. README.

    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py free --season 36       # 0a 규칙 없는 표(끊기면 같은 명령)
    python -I experiments/42_bundle_search/run42.py freepack --season 36                                    # 0b 규칙 없는 OPT(시뮬 0)
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py ordercheck --season 36  # 0c 단계 안 순서 × 카메라
    python -I experiments/42_bundle_search/run42.py replay --season 36 --arm P --seed 0                     # 1단계(시뮬 0)
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py check39                 # 2단계 전: 실험 39 base 300덱 다시 재기
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py run --arm P --season 23,24  # 2단계(B_s0 · B_s1)
    source .cache/evaluators.env && python -I experiments/42_bundle_search/run42.py order --arm base,P      # 3단계 순서 분리
    python -I experiments/42_bundle_search/run42.py analyze                                                 # 시뮬 0 → analysis.json · results.md

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


# ---------------------------------------------------------------- 2단계 검증(S23~S32, 실제 시뮬)

BASE39 = EXPS / "39_bundle_explore" / "run_log" / "base"
CHECK39_N = 300
VERIFY_ARMS = ("R", "P", "L", "P50", "PL")
GATE_ARMS = ("P", "L", "P50", "PL")   # 판단 2 후보(P · L과 그 개발 변형)


def r39() -> Any:
    """실험 39(검증 시즌 · 시드 · 판정 · 놓친 몫 요약). 불러오면 run31이 검증 시즌 자료도 읽는다."""
    return sys.modules.get("run39") or _load("run39", EXPS / "39_bundle_explore" / "run39.py")


def vdir(arm: str, s: int) -> Path:
    return LOG / "verify" / arm / f"S{int(s):02d}"


def verify_recs(arm: str, s: int, k: int) -> list[dict[str, Any]]:
    """2단계 기록: base는 실험 39 base 기록(같은 계정 · 난수 · 예산), 판은 이 실험 기록."""
    p = (BASE39 / f"S{int(s):02d}" if arm == "base" else vdir(arm, s)) / f"B_s{k}.jsonl.gz"
    return run31.load_recs(p)


def cmd_check39(a: argparse.Namespace) -> int:
    """2단계 전: 실험 39 base 기록에서 무작위 300덱을 지금 평가기로 다시 재 같은 값인지 본다."""
    from nikke_opt.evaluator import EvalRequest
    import random
    R39 = r39()
    f = LOG / "verify" / "check39.json"
    if f.exists() and not a.force:
        print(f.read_text(encoding="utf-8"))
        return 0
    cand = [(s, k, j, r) for s in R39.SEASONS for k in R39.SEEDS
            for j, r in enumerate(verify_recs("base", s, k)) if r.get("error") is None and r.get("total_damage") is not None]
    pick = random.Random(42042).sample(cand, CHECK39_N)
    t0 = time.time()
    with R41.evaluator(a.jobs) as ev:
        res = ev.evaluate([EvalRequest(list(r["squad"]), boss=None, options=run31.options(s, 0)) for s, _, _, r in pick])
        ver = R41.ev_version(ev)
    diff = [{"season": s, "seed": k, "rec": j, "squad": r["squad"], "was": r["total_damage"], "now": x.total_damage}
            for (s, k, j, r), x in zip(pick, res) if x.total_damage != r["total_damage"]]
    base_ver = sorted({(jload(BASE39 / f"S{s:02d}" / f"part_B_s{k}.json") or {}).get("evaluator") for s in R39.SEASONS for k in R39.SEEDS})
    out = {"n": len(pick), "diff": len(diff), "examples": diff[:10], "evaluator": ver, "base_evaluators": base_ver,
           "seconds": round(time.time() - t0, 1)}
    jdump(f, out)
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0 if not diff else 1


def cmd_run(a: argparse.Namespace) -> int:
    """2단계: 고정한 판을 검증 시즌에서 실제 시뮬로(실험 39 `run`과 같은 계정 · 예산 · 시드). 부분 B_s0 · B_s1."""
    R39 = r39()
    A = arms_mod()
    with R41.evaluator(a.jobs) as ev:
        ver = R41.ev_version(ev)
        for s in [int(x) for x in str(a.season).split(",")]:
            if s not in R39.SEASONS:
                raise SystemExit(f"S{s}는 검증 시즌이 아니다({R39.SEASONS[0]}~{R39.SEASONS[-1]})")
            for part in a.part.split(","):
                k = int(part.removeprefix("B_s"))
                pf = vdir(a.arm, s) / f"part_{part}.json"
                if pf.exists():
                    continue
                n0, t0 = ev.sim_count, time.time()
                summ, recs, sess = run_arm(run31.account(s, k), a.arm, R39.SEED_BUDGET, ev)
                run31.write_recs(vdir(a.arm, s) / f"{part}.jsonl.gz", recs)
                out = {"arm": a.arm, "params": dict(A.PARAMS), "season": s, "seed": k, "budget": R39.SEED_BUDGET,
                       "evals": summ["evals"], "seconds": summ["seconds"], "best": summ["final"]["total"], "errors": summ["errors"],
                       "kicks": len(summ["kicks"]), "history": summ["history"],
                       "outside_rule_requests": sum(not P41.passes(r["squad"]) for r in recs),
                       "final_outside_rule": sum(not P41.passes(q) for _, q in summ["final"]["squads"]),
                       "part": part, "evaluator": ver, "sims": ev.sim_count - n0, "wall": round(time.time() - t0, 1)}
                jdump(pf, out)
                print(json.dumps({k2: v for k2, v in out.items() if k2 != "history"}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 3단계 순서 분리(실제 시뮬, 작음)

def cam_options(s: int, name: str | None) -> dict[str, Any]:
    o = run31.options(s, 0)
    if name is not None:
        o["operation"] = {**o.get("operation", {}), "camera": name}
    return o


def order_season(arm: str, s: int, ev: Any) -> dict[str, Any]:
    """두 시드 기록을 합친 최선 5덱 + 값 상위 20 구성에 「단계 안 순서(stage_key 대표 전부) → 최선 순서에서 카메라 5명」을 얹는다.
    잰 적 있는 stage_key는 다시 재지 않는다(기록 값을 쓴다). 다듬은 값으로 다시 묶어 5덱 합 · 덱 바뀜을 본다."""
    from nikke_opt.evaluator import EvalRequest
    R39 = r39()
    recs = [r for k in R39.SEEDS for r in verify_recs(arm, s, k)]
    meas: dict[tuple, float] = {}
    for r in recs:
        if r.get("total_damage") is not None:
            o = tuple(r["squad"])
            meas[o] = max(meas.get(o, float("-inf")), r["total_damage"] / E8)
    bk = R41.R30.book_of(recs)
    pre_v, pre_d = R9.pack_vals(bk)
    top = [c for c, _ in sorted(bk.items(), key=lambda kv: (-kv[1][0], kv[1][1]))[:R9.ORDER_TOP]]
    targets = list(dict.fromkeys([frozenset(q) for _, q in pre_d] + top))
    sk = lambda o: R41.R2.stage_key(o, BURST)  # noqa: E731
    by_comp: dict[frozenset, dict[tuple, float]] = {}
    for o, v in meas.items():
        if frozenset(o) in targets:
            by_comp.setdefault(frozenset(o), {})[o] = v
    todo = []
    for c in targets:
        have = {sk(o) for o in by_comp[c]}
        todo += [o for o in R41.R2.distinct_orders(bk[c][1], BURST) if sk(o) not in have]
    n0 = ev.sim_count
    res = ev.evaluate([EvalRequest(list(o), boss=None, options=cam_options(s, None)) for o in todo])
    for o, x in zip(todo, res):
        if x.error is None and x.total_damage is not None:
            by_comp[frozenset(o)][o] = x.total_damage / E8
    best_o = {c: max(d.items(), key=lambda kv: (kv[1], kv[0])) for c, d in by_comp.items()}
    cams = [(c, n) for c in targets for n in best_o[c][0]]
    res = ev.evaluate([EvalRequest(list(best_o[c][0]), boss=None, options=cam_options(s, n)) for c, n in cams])
    cam_v: dict[frozenset, dict[str, float]] = {}
    for (c, n), x in zip(cams, res):
        if x.error is None and x.total_damage is not None:
            cam_v.setdefault(c, {})[n] = x.total_damage / E8
    sims = ev.sim_count - n0
    bk_o = dict(bk)
    bk_c = dict(bk)
    decks = []
    for c in targets:
        o, v = best_o[c]
        bk_o[c] = (v, o) if v > bk[c][0] else bk[c]
        cv = cam_v.get(c, {})
        n_best = max(cv, key=lambda n: (cv[n], n)) if cv else None
        vc = max([bk_o[c][0]] + list(cv.values()))
        bk_c[c] = (vc, bk_o[c][1])
        decks.append({"comp": sorted(c), "pre": bk[c][0], "pre_order": list(bk[c][1]), "order": v, "best_order": list(o),
                      "orders": len(by_comp[c]), "camera": cv, "best_camera": n_best, "after": vc,
                      "outside_rule": not P41.passes(sorted(c))})
    ov, od = R9.pack_vals(bk_o)
    cv_, cd = R9.pack_vals(bk_c)
    same = lambda d: {frozenset(q) for _, q in d} == {frozenset(q) for _, q in pre_d}  # noqa: E731
    return {"arm": arm, "season": s, "pre": pre_v, "after_order": ov, "after_camera": cv_,
            "gain_order": ov / pre_v - 1, "gain_camera": cv_ / ov - 1, "gain": cv_ / pre_v - 1,
            "repacked_order": not same(od), "repacked_camera": not same(cd),
            "final": [[v, list(q)] for v, q in cd], "decks": decks, "targets": len(targets), "order_sims": len(todo),
            "camera_sims": len(cams), "sims": sims}


def cmd_order(a: argparse.Namespace) -> int:
    R39 = r39()
    arms = a.arm.split(",")
    with R41.evaluator(a.jobs) as ev:
        ver = R41.ev_version(ev)
        for arm in arms:
            for s in R39.SEASONS:
                f = LOG / "order" / arm / f"S{s:02d}.json"
                if f.exists():
                    continue
                if any(not verify_recs(arm, s, k) for k in R39.SEEDS):
                    print(f"{arm} S{s}: 2단계 기록 없음 — 건너뜀", flush=True)
                    continue
                t0 = time.time()
                out = order_season(arm, s, ev) | {"evaluator": ver, "seconds": round(time.time() - t0, 1)}
                jdump(f, out)
                print(json.dumps({k: out[k] for k in ("arm", "season", "pre", "after_order", "after_camera", "gain_order", "gain_camera",
                                                      "repacked_camera", "sims")}, ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 요약(시뮬 0)

GAIN_MIN = 0.005          # 판단 1: 규칙 밖 몫
REACH_MIN = 3             # 판단 2: 99% 도달 시드 수(4개 중)
S39_SLACK = 0.002         # 판단 2: S39 시드 중앙이 base보다 이만큼 넘게 낮으면 안 된다
PICK_TIE = 0.002          # 판단 2: 두 판 12,500 시드 중앙 차이가 이 안이면 둘 다
COVER_MIN, COVER_SHARE = 0.99, 0.90   # 판단 4
DEV_GATE = (36, 42)       # 판단 2: 99% 도달을 보는 시즌
DEV_GUARD = 39            # 판단 2: base보다 낮지 않아야 하는 시즌


def med(xs: Sequence[float | None]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def replay_rows(s: int, tag: str) -> list[dict[str, Any]]:
    out = []
    for k in REPLAY_SEEDS:
        d = jload(sdir(s) / "replay" / f"{tag}_s{k}.json")
        if d:
            out.append({x: d[x] for x in ("seed", "evals", "final_ratio", "final_ratio_rule", "reach", "final_outside_rule",
                                          "outside_rule_requests", "comps_seen", "seconds", "params")})
    return out


def analyze() -> dict[str, Any]:
    out: dict[str, Any] = {"free": {}, "replay": {}, "judge": {}}
    # 0b · 판단 1
    for s in SEASONS:
        fp = jload(sdir(s) / "freepack.json")
        if fp:
            out["free"][str(s)] = {"opt": fp["opt"]["total"], "exact": fp["opt"].get("exact"), "rule_opt": fp["rule_opt_base"],
                                   "gain": fp["gain_vs_rule"], "ranks": fp["opt"]["ranks"], "outside_rule": fp["opt"]["outside_rule"],
                                   "landscape": fp["landscape"], "classes": fp["classes"],
                                   "r_need": {k: v.get("K") for k, v in fp["r_need"].items()}}
    if out["free"]:
        out["judge"]["1"] = {"seasons": len(out["free"]), "gain_ge": sum(v["gain"] >= GAIN_MIN for v in out["free"].values())}
    # 1단계 · 판단 2
    for s in SEASONS:
        for tag in ("base",) + VERIFY_ARMS:
            rows = replay_rows(s, tag)
            if rows:
                out["replay"].setdefault(str(s), {})[tag] = {
                    "seeds": rows, "n": len(rows), "median": med([r["final_ratio"] for r in rows]),
                    "min": min(r["final_ratio"] for r in rows), "median_rule": med([r["final_ratio_rule"] for r in rows]),
                    "reach99": sum(r["reach"]["0.99"] is not None for r in rows), "reach97": sum(r["reach"]["0.97"] is not None for r in rows),
                    "reach99_evals": med([r["reach"]["0.99"] for r in rows]), "seconds": med([r["seconds"] for r in rows])}
    rp = out["replay"]
    done = lambda t: all(len(rp.get(str(s), {}).get(t, {}).get("seeds", [])) == len(REPLAY_SEEDS) for s in SEASONS)  # noqa: E731
    if done("base"):
        passed = {}
        for arm in GATE_ARMS:
            if not done(arm):
                continue
            gate = {s: rp[str(s)][arm]["reach99"] for s in DEV_GATE}
            guard = rp[str(DEV_GUARD)][arm]["median"] - rp[str(DEV_GUARD)]["base"]["median"]
            allm = med([r["final_ratio"] for s in SEASONS for r in rp[str(s)][arm]["seeds"]])
            ok = all(v >= REACH_MIN for v in gate.values()) and guard >= -S39_SLACK
            passed[arm] = {"reach99": gate, "s39_vs_base": guard, "median_all": allm, "pass": ok}
        ok = sorted((a for a, v in passed.items() if v["pass"]), key=lambda a: -passed[a]["median_all"])
        ok = [a for a in ok if passed[ok[0]]["median_all"] - passed[a]["median_all"] <= PICK_TIE][:2]
        if passed:
            out["judge"]["2"] = {"arms": passed, "to_stage2": ok}
    # 2단계 · 판단 3
    R39 = r39()
    vrows: dict[str, dict[int, dict[str, Any]]] = {}
    for arm in ("base",) + VERIFY_ARMS:
        for s in R39.SEASONS:
            recs = {k: verify_recs(arm, s, k) for k in R39.SEEDS}
            if any(not v for v in recs.values()):
                continue
            row = {"season": s, **R39.summarize(s, R41.R30.book_of([r for k in R39.SEEDS for r in recs[k]]))}
            row["seed"] = {k: R39.summarize(s, R41.R30.book_of(recs[k]))["pack"] for k in R39.SEEDS}
            if arm != "base":
                parts = [jload(vdir(arm, s) / f"part_B_s{k}.json") or {} for k in R39.SEEDS]
                row["outside_rule_requests"] = sum(p.get("outside_rule_requests", 0) for p in parts)
                row["final_outside_rule"] = [p.get("final_outside_rule") for p in parts]
                row["wall"] = sum(p.get("wall", 0) for p in parts)
            vrows.setdefault(arm, {})[s] = row
    out["verify"] = {arm: list(v.values()) for arm, v in vrows.items()}
    base = vrows.get("base", {})
    cmp_ = {}
    for arm in VERIFY_ARMS:
        pair = [(r, base[s]) for s, r in vrows.get(arm, {}).items() if s in base]
        if not pair:
            continue
        rs = [r["pack"] / b["pack"] - 1 for r, b in pair]
        cmp_[arm] = {"seasons": [r["season"] for r, _ in pair], "ratio": rs, "median": med(rs), "drops": sum(x < R39.DROP for x in rs),
                     "per_seed_median": med([r["seed"][k] / b["seed"][k] - 1 for r, b in pair for k in R39.SEEDS]),
                     "G_arm": med([r["G"] for r, _ in pair]), "G_base": med([b["G"] for _, b in pair]),
                     "visit_arm": med([r["visit"] for r, _ in pair]), "visit_base": med([b["visit"] for _, b in pair]),
                     "verdict": R39.verdict(rs) if len(pair) == len(R39.SEASONS) else f"진행 중 {len(pair)}/{len(R39.SEASONS)}"}
    if cmp_:
        out["judge"]["3"] = cmp_
    # 3단계 · 판단 4
    oc = [jload(sdir(s) / "ordercheck_summary.json") for s in SEASONS]
    if all(oc):
        n = sum(o["comps"] for o in oc)
        full = sum(o["cover_full"]["ge_99"] for o in oc)
        cheap = sum(o["cover_cheap"]["ge_99"] for o in oc)
        out["judge"]["4"] = {"comps": n, "full_ge99": full, "cheap_ge99": cheap, "share": full / n, "pass": full / n >= COVER_SHARE}
    od: dict[str, list[dict[str, Any]]] = {}
    for arm in ("base",) + VERIFY_ARMS:
        for s in R39.SEASONS:
            d = jload(LOG / "order" / arm / f"S{s:02d}.json")
            if d:
                od.setdefault(arm, []).append({k: d[k] for k in ("season", "pre", "after_order", "after_camera", "gain_order", "gain_camera",
                                                                 "gain", "repacked_order", "repacked_camera", "sims")})
    out["order"] = {arm: {"rows": v, "gain_median": med([r["gain"] for r in v]), "gain_camera_median": med([r["gain_camera"] for r in v]),
                          "repacked": sum(r["repacked_camera"] for r in v)} for arm, v in od.items()}
    ob = {r["season"]: r for r in od.get("base", [])}
    for arm in VERIFY_ARMS:
        pair = [(r, ob[r["season"]]) for r in od.get(arm, []) if r["season"] in ob]
        if pair:
            out["order"][arm]["ratio_after"] = med([r["after_camera"] / b["after_camera"] - 1 for r, b in pair])
    return out


def pct(x: float | None, d: int = 2, sign: bool = True) -> str:
    return "—" if x is None else f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"


def write_md(an: Mapping[str, Any]) -> str:
    L = ["# 실험 42 결과 표", "", "`run42.py analyze`가 만든다. 값 단위 억(기본 순서 · 코어 없음 · 기본 레이어).", ""]
    if an["free"]:
        L += ["## 0b 규칙 없는 OPT", "", "| 시즌 | OPT_free | 규칙 공간 OPT | 차이 | 규칙 밖 덱 | 5덱 개별 순위 | R_need(99%) |", "|---|---|---|---|---|---|---|"]
        for s, v in an["free"].items():
            L.append(f"| S{s} | {v['opt']:.2f} | {v['rule_opt']:.2f} | {pct(v['gain'])} | {len(v['outside_rule'])} | "
                     f"{', '.join(f'{x:,}' for x in v['ranks'])} | {v['r_need'].get('0.99') or '—'} |")
        L.append("")
    if an["replay"]:
        L += ["## 1단계 재생(기본 값 세계, 12,500평가, 시드 4)", "", "| 시즌 | 판 | ÷ OPT_free 중앙 | 최소 | ÷ 규칙 OPT 중앙 | 99% 도달 | 97% 도달 | 99% 도달 평가(중앙) | 시간(초) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for s, arms in an["replay"].items():
            for tag, v in arms.items():
                L.append(f"| S{s} | {tag} | {pct(v['median'], sign=False)} | {pct(v['min'], sign=False)} | {pct(v['median_rule'], sign=False)} | "
                         f"{v['reach99']}/{v['n']} | {v['reach97']}/{v['n']} | {v['reach99_evals'] or '—'} | {v['seconds']:.0f} |")
        L.append("")
    if an.get("verify"):
        L += ["## 2단계 검증(S23~S32, 두 시드 합쳐 묶은 최선 5덱)", ""]
        arms = list(an["verify"])
        L += ["| 시즌 | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        by = {a: {r["season"]: r for r in an["verify"][a]} for a in arms}
        b = by.get("base", {})
        for s in sorted({s for v in by.values() for s in v}):
            cells = []
            for a in arms:
                r = by[a].get(s)
                cells.append("—" if not r else f"{r['pack']:.1f}" + (f" ({pct(r['pack'] / b[s]['pack'] - 1)})" if a != "base" and s in b else ""))
            L.append(f"| S{s} | " + " | ".join(cells) + " |")
        L.append("")
    for k, v in an["judge"].items():
        L.append(f"- 판단 {k}: `{json.dumps(v, ensure_ascii=False)}`")
    if an.get("order"):
        L += ["", "## 3단계 순서 분리(최종 5덱 + 값 상위 20에 단계 안 순서 × 카메라)", ""]
        for arm, v in an["order"].items():
            L.append(f"- {arm}: 5덱 합 이득 중앙 {pct(v['gain_median'])} (카메라 몫 {pct(v['gain_camera_median'])}) · 다시 묶어 덱이 바뀐 시즌 {v['repacked']}"
                     + (f" · 다듬은 뒤 ÷ base 중앙 {pct(v['ratio_after'])}" if "ratio_after" in v else ""))
    return "\n".join(L) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    an = analyze()
    jdump(HERE / "analysis.json", an)
    md = write_md(an)
    (HERE / "results.md").write_text(md, encoding="utf-8")
    print(md)
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
    y.add_argument("--arm", required=True, choices=("base", "R", "P", "L", "P50", "PL"))
    y.add_argument("--seed", type=int, default=None)
    y.add_argument("--budget", type=int, default=REPLAY_BUDGET)
    y.add_argument("--tag", default=None, help="기록 이름(개발 중 판 수치를 바꿔 볼 때)")
    y.add_argument("--force", action="store_true")
    v = sub.add_parser("check39")
    v.add_argument("--jobs", type=int, default=4)
    v.add_argument("--force", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--arm", required=True, choices=VERIFY_ARMS)
    r.add_argument("--season", required=True, help="쉼표로 여럿")
    r.add_argument("--part", default="B_s0,B_s1")
    r.add_argument("--jobs", type=int, default=4)
    o = sub.add_parser("order")
    o.add_argument("--arm", required=True, help="base · R · P · L(쉼표로 여럿)")
    o.add_argument("--jobs", type=int, default=4)
    sub.add_parser("analyze")
    a = p.parse_args(argv)
    return {"free": cmd_free, "ordercheck": cmd_ordercheck, "freepack": cmd_freepack, "replay": cmd_replay, "check39": cmd_check39,
            "run": cmd_run, "order": cmd_order, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
