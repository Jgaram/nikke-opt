"""실험 41 — 답안지: 작은 풀 전수 계산으로 풀 안의 최적 5덱(OPT)을 알고 탐색 · 랭커 · 실전을 채점한다. README.

    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py check --season 36     # 평가기 대조(실험 36 기록)
    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py table --season 36     # 1단계 · 끊기면 같은 명령
    source .cache/evaluators.env && python -I experiments/41_ground_truth/run41.py refine --season 36    # 2단계
    python -I experiments/41_ground_truth/run41.py pack --season 36                                      # 3단계(시뮬 0)
    python -I experiments/41_ground_truth/run41.py replay --season 36 --seed 0                           # 4단계(시뮬 0)
    python -I experiments/41_ground_truth/run41.py analyze                                               # → analysis.json · results.md

- 값 = 기본 레이어 1시뮬 사전 값: 실험 31 `options`(시즌 보스 속성 · 그때 없던 애장품 0단계) + `sim.camera_reload_cancel`
  (사용자 결정 2026-11-04 「켬」). 코어 없음, 계산기 기본 스펙. 평가기는 nikke-calc-rs master(`83a6d54` 이후).
- 1단계 표는 `run_log/S??/table/c????.jsonl.gz`(구성 CHUNK개씩)에 쓴다. 조각이 있으면 건너뛰므로 끊기면 같은 명령으로 잇는다.
  줄 = [구성 번호(pool41.iter_comps 순), 값(억), 니케별 딜(억, 배치 순서대로)] — 배치 순서는 `base_order`로 다시 만든다.
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import random
import sys
import time
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


P41 = sys.modules.get("pool41") or _load("pool41", HERE / "pool41.py")
run31 = sys.modules.get("run31") or _load("run31", EXPS / "31_recent_seasons" / "run31.py")
R10, R9, R30, R2 = run31.R10, run31.R9, run31.R30, run31.R9.R2
E8 = 1e8

# ---------------------------------------------------------------- 정한 값(README — 사용자 결정 2026-11-04)
CAMERA_RELOAD_CANCEL = True    # 평가기 옵션 켬(사용자 결정)
SEASONS = P41.SEASONS          # (36, 39, 42)
CHUNK = 5000
LOG = Path(os.environ.get("NIKKE41_LOG") or HERE / "run_log")   # 실행 중에는 레포 밖 작업 폴더에 쓰고 옮겨 커밋할 수 있다
EXP36_LOG = EXPS / "36_season_refresh" / "run_log"
POOLS = json.loads(P41.OUT.read_text(encoding="utf-8"))["seasons"] if P41.OUT.exists() else {}
BURST = P41.BURST


def sdir(s: int) -> Path:
    return LOG / f"S{int(s):02d}"


def jload(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def jdump(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def pool(s: int) -> list[str]:
    return list(POOLS[str(s)]["pool"])


def options(s: int) -> dict[str, Any]:
    o = run31.options(s, 0)
    if CAMERA_RELOAD_CANCEL:
        o["sim"] = {**o.get("sim", {}), "camera_reload_cancel": True}
    return o


def base_order(comp: Sequence[str]) -> tuple[str, ...]:
    """기본 배치 순서: 단계 1 · 2 · A · 3(실험 10 `arrange`), 같은 단계 안은 이름순."""
    names = sorted(comp)
    return tuple(n for st in "12A3" for n in names if BURST[n] == st)


def comps(s: int) -> list[tuple[str, ...]]:
    return list(P41.iter_comps(pool(s)))


def evaluator(jobs: int = 4) -> Any:
    from nikke_opt.evaluator import make_evaluator
    return make_evaluator("rust", jobs=jobs, cache=False)


def ev_version(ev: Any) -> str:
    v = ev.version
    return f"{v.get('repo')} {str(v.get('commit'))[:7]}" + (" dirty" if v.get("dirty") else "")


def run_orders(s: int, orders: Sequence[Sequence[str]], ev: Any) -> list[tuple[float | None, list[float] | None]]:
    """배치 순서마다 (값(억), 니케별 딜(억, 배치 순서대로))."""
    from nikke_opt.evaluator import EvalRequest
    o = options(s)
    res = ev.evaluate([EvalRequest(tuple(q), boss=None, options=o) for q in orders])
    out = []
    for q, r in zip(orders, res):
        if r.error or r.total_damage is None:
            out.append((None, None))
            continue
        dmg = {x["name"]: x["damage"] for x in r.raw.get("members", [])}
        out.append((r.total_damage / E8, [round(dmg.get(n, 0) / E8, 4) for n in q]))
    return out


# ---------------------------------------------------------------- 대조: 카메라 옵션을 켠 값이 실험 36 사전 값과 같은가

def cmd_check(a: argparse.Namespace) -> int:
    """실험 36 기록(랭커 덱 rankers.json 코어 없음 · B_s0 무작위 a.n개)을 이 실험의 options로 다시 재 차이를 센다."""
    out = {}
    with evaluator(a.jobs) as ev:
        for s in [int(x) for x in str(a.season).split(",")]:
            d = EXP36_LOG / f"S{s}"
            rk = jload(d / "rankers.json")["squads"]
            pairs = [(tuple(k.split(",")), v["nocore"]) for k, v in rk.items() if v.get("nocore") is not None]
            recs = [r for r in run31.load_recs(d / "B_s0.jsonl.gz") if r.get("total_damage") is not None]
            rng = random.Random(f"exp41-check-{s}")
            pairs += [(tuple(r["squad"]), r["total_damage"] / E8) for r in rng.sample(recs, min(a.n, len(recs)))]
            t0, n0 = time.time(), ev.sim_count
            got = run_orders(s, [q for q, _ in pairs], ev)
            diffs = [(q, old, new) for (q, old), (new, _) in zip(pairs, got) if new is None or abs(new - old) > 1e-6]
            out[str(s)] = {"decks": len(pairs), "diff": len(diffs), "examples": [[list(q), old, new] for q, old, new in diffs[:5]],
                           "sims": ev.sim_count - n0, "seconds": round(time.time() - t0, 1), "evaluator": ev_version(ev),
                           "sims_per_s": round((ev.sim_count - n0) / max(time.time() - t0, 1e-9), 2)}
            print(json.dumps({"season": s, **out[str(s)]}, ensure_ascii=False), flush=True)
    prev = jload(LOG / "check.json") or {}
    jdump(LOG / "check.json", {**prev, **out, "camera_reload_cancel": CAMERA_RELOAD_CANCEL})
    return 0


# ---------------------------------------------------------------- 1단계: 전수 표

def chunk_file(s: int, k: int) -> Path:
    return sdir(s) / "table" / f"c{k:04d}.jsonl.gz"


def iter_table(s: int) -> Iterator[list]:
    """표 줄 [번호, 값, 니케별 딜] — 조각 순서대로."""
    for f in sorted((sdir(s) / "table").glob("c*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)


def load_table(s: int) -> tuple[list[tuple[str, ...]], list[float | None]]:
    """(구성 목록, 기본 순서 값) — 값이 없는 구성(오류 · 아직 안 돈 조각)은 None."""
    cs = comps(s)
    vals: list[float | None] = [None] * len(cs)
    for i, v, _ in iter_table(s):
        vals[i] = v
    return cs, vals


def cmd_table(a: argparse.Namespace) -> int:
    s = a.season
    cs = comps(s)
    assert len(cs) == POOLS[str(s)]["comps"], (len(cs), POOLS[str(s)]["comps"])
    n_chunks = (len(cs) + CHUNK - 1) // CHUNK
    meta_f = sdir(s) / "table_meta.json"
    meta = jload(meta_f) or {"season": s, "comps": len(cs), "chunk": CHUNK, "chunks": n_chunks, "options": options(s),
                             "order": "단계 1 · 2 · A · 3, 같은 단계 안 이름순", "parts": {}}
    with evaluator(a.jobs) as ev:
        ver = ev_version(ev)
        for k in range(n_chunks):
            f = chunk_file(s, k)
            if f.exists():
                continue
            if a.limit is not None and a.limit <= 0:
                break
            idx = list(range(k * CHUNK, min((k + 1) * CHUNK, len(cs))))
            orders = [base_order(cs[i]) for i in idx]
            t0, n0 = time.time(), ev.sim_count
            got = run_orders(s, orders, ev)
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                for i, (v, m) in zip(idx, got):
                    fh.write(json.dumps([i, v, m], ensure_ascii=False) + "\n")
            tmp.rename(f)
            sec = time.time() - t0
            meta["parts"][str(k)] = {"sims": ev.sim_count - n0, "seconds": round(sec, 1),
                                     "errors": sum(v is None for v, _ in got), "evaluator": ver}
            jdump(meta_f, meta)
            done = len(meta["parts"])
            print(f"S{s} 조각 {k + 1}/{n_chunks} ({done} 끝) {ev.sim_count - n0}시뮬 {sec:.0f}초 "
                  f"{(ev.sim_count - n0) / max(sec, 1e-9):.1f}/초", flush=True)
            if a.limit is not None:
                a.limit -= 1
    return 0


# ---------------------------------------------------------------- 표(값 모음) — 묶기 · 순위 · 재생이 쓴다(시뮬 0)

def stage_key(order: Sequence[str]) -> tuple:
    """딜에 영향을 주는 순서 정보(실험 2 `stage_key`): 단계마다(A 포함) 그 단계 니케의 순서."""
    return R2.stage_key(tuple(order), BURST)


class Table:
    """한 시즌의 답안지 표. 구성 i: cs[i](이름순), base[i](기본 순서 값), ref[i](다듬은 값 = 잰 순서 중 최고), best_order[i]."""

    def __init__(self, s: int, cs: Sequence[tuple[str, ...]], base: Sequence[float | None],
                 refined: Mapping[int, Mapping[tuple, tuple[float, tuple]]] | None = None, pool_names: Sequence[str] | None = None):
        self.s, self.cs = s, list(cs)
        self.idx = {frozenset(c): i for i, c in enumerate(self.cs)}
        self.base = [None if v is None else float(v) for v in base]
        names = sorted({n for c in self.cs for n in c}) if pool_names is None else sorted(pool_names)
        self.bit = {n: k for k, n in enumerate(names)}
        self.masks = [sum(1 << self.bit[n] for n in c) for c in self.cs]
        self.refined = {i: dict(d) for i, d in (refined or {}).items()}   # i → {stage_key: (값, 순서)}
        self.ref: list[float | None] = list(self.base)
        self.best_order: list[tuple] = [base_order(c) for c in self.cs]
        for i, d in self.refined.items():
            for v, o in d.values():
                if v is not None and (self.ref[i] is None or v > self.ref[i]):
                    self.ref[i], self.best_order[i] = v, tuple(o)

    @classmethod
    def load(cls, s: int, with_refine: bool = True) -> "Table":
        cs, vals = load_table(s)
        missing = sum(v is None for v in vals)
        if missing:
            meta = jload(sdir(s) / "table_meta.json") or {}
            errs = sum(p.get("errors", 0) for p in meta.get("parts", {}).values())
            if missing > errs:
                raise RuntimeError(f"S{s} 표가 덜 됐다: 값 없는 구성 {missing:,} (오류 {errs})")
        return cls(s, cs, vals, load_refine(s) if with_refine else None, pool(s))

    def values(self, kind: str) -> list[float | None]:
        return self.base if kind == "base" else self.ref

    def order_of(self, kind: str, i: int) -> tuple:
        return base_order(self.cs[i]) if kind == "base" else self.best_order[i]

    def sorted_idx(self, kind: str) -> list[int]:
        """값 내림차순(같으면 구성 이름순). 값 없는 구성은 뺀다."""
        v = self.values(kind)
        return sorted((i for i in range(len(self.cs)) if v[i] is not None), key=lambda i: (-v[i], self.cs[i]))

    def ranks(self, kind: str) -> dict[int, int]:
        return {i: r + 1 for r, i in enumerate(self.sorted_idx(kind))}

    def book(self, kind: str, idx: Sequence[int]) -> dict[frozenset, tuple[float, tuple]]:
        v = self.values(kind)
        return {frozenset(self.cs[i]): (v[i], self.order_of(kind, i)) for i in idx if v[i] is not None}


def load_refine(s: int) -> dict[int, dict[tuple, tuple[float, tuple]]]:
    """2단계 기록 + 기본 순서 값을 구성마다 {stage_key: (값, 순서)}로."""
    f = sdir(s) / "refine.jsonl.gz"
    if not f.exists():
        return {}
    out: dict[int, dict[tuple, tuple[float, tuple]]] = {}
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["value"] is not None:
                out.setdefault(r["i"], {})[stage_key(r["order"])] = (r["value"], tuple(r["order"]))
    return out


# ---------------------------------------------------------------- 3단계 도구: 상한 가지치기 · 정확 묶기 · 경치 · R_need

LAG_SLACK = 1e-6       # 라그랑주 상한의 부동소수 여유(실험 9 PACK_SLACK과 같다)
PRUNE_PASSES = 3


def _lag(vs: Any, inc: Any, m: int, k: int, thr: float) -> Any:
    """니케별 λ ≥ 0(실험 9 `_pack_lagrange` — 겹치지 않는 k덱 합의 쌍대 상한을 thr 쪽으로 줄이는 λ)."""
    import numpy as np
    return np.asarray(R9._pack_lagrange(list(vs), inc, m, k, inc.shape[1], thr), dtype=float)


def prune(T: Table, kind: str, thr: float, k: int = 5) -> tuple[list[int], dict[str, Any]]:
    """합 ≥ thr인 겹치지 않는 k덱에 들 수 있는 구성(값 순). 아래 상한 중 하나라도 thr 미만이면 뺀다.

    - 라그랑주: 덱 P ∋ i의 합 ≤ v(i) + (i 말고 감한 값 red = v − Σλ 상위 k−1개) + (i에 없는 니케의 λ 상위 5(k−1)개).
    - 겹치지 않는 값: v(i) + (i와 니케가 겹치지 않는 남은 후보 중 값 상위 k−1개).
    합 ≥ thr인 덱의 구성은 모두 살아남으므로 남은 후보 안에서 다시 재도 맞다 → 줄지 않을 때까지(최대 PRUNE_PASSES번) 되풀이한다."""
    import numpy as np
    v = T.values(kind)
    keep = T.sorted_idx(kind)
    m = len(T.bit)
    info: dict[str, Any] = {"start": len(keep), "passes": []}
    need = 5 * (k - 1)
    for _ in range(PRUNE_PASSES):
        n0 = len(keep)
        if n0 < k:
            break
        vs = np.array([v[i] for i in keep], dtype=float)
        inc = np.array([[T.bit[x] for x in T.cs[i]] for i in keep], dtype=np.int64)
        lam = _lag(vs, inc, m, k, thr)
        red = vs - lam[inc].sum(1)
        top = np.argsort(-red, kind="stable")[:k]
        s_k1 = float(red[top[:k - 1]].sum())
        others = np.full(n0, s_k1)
        others[top[:k - 1]] = s_k1 - red[top[:k - 1]] + red[top[k - 1]]
        L = np.argsort(-lam, kind="stable")[:min(m, need + inc.shape[1])]
        mem = (inc[:, :, None] == L[None, None, :]).any(1)
        free = ~mem
        sel = free & (np.cumsum(free, axis=1) <= need)
        lam_part = (sel * lam[L][None, :]).sum(1)
        ub = vs + others + lam_part
        keep = [i for i, u in zip(keep, ub) if u + LAG_SLACK >= thr]
        # 겹치지 않는 값 상한(남은 후보 안에서)
        if len(keep) >= k:
            om = np.array([T.masks[j] for j in keep], dtype=np.uint64)
            ov = np.array([v[j] for j in keep], dtype=float)
            ok = []
            for i in keep:
                hit = np.flatnonzero((om & np.uint64(T.masks[i])) == 0)[:k - 1]
                if len(hit) == k - 1 and v[i] + float(ov[hit].sum()) + 1e-9 >= thr:
                    ok.append(i)
            keep = ok
        info["passes"].append(len(keep))
        if len(keep) == n0:
            break
    return keep, info


SEED_LIMITS = (5000, 20000, 80000)


def exact_opt(T: Table, kind: str, seed_limit: int | None = None, deadline_s: float = 3600.0) -> dict[str, Any]:
    """OPT: 값 상위 seed_limit로 하한 LB → 상한 < LB 구성 빼기 → 남은 구성으로 정확히 묶기(`pack_vals`).
    값 상위 몇천 구성은 같은 강한 니케를 나눠 써서 겹치지 않는 5덱이 안 나올 수 있다(S36 상위 5,000) → 5덱이 나올 때까지 넓힌다."""
    t0 = time.time()
    order = T.sorted_idx(kind)
    lb, lb_decks = 0.0, []
    for lim in ((seed_limit,) if seed_limit else SEED_LIMITS):
        seed_limit = lim
        lb, lb_decks = R9.pack_vals(T.book(kind, order[:lim]))
        if lb_decks:
            break
    keep, pinfo = prune(T, kind, lb - 1e-9)
    exact = True
    try:
        total, decks = R9.pack_vals(T.book(kind, keep), deadline=time.monotonic() + deadline_s)
    except R9.PackTimeout as e:
        total, decks, exact = e.total, e.decks, False
    if total < lb - 1e-9:                     # 시간 초과로 하한보다 낮게 끝나면 하한 해
        total, decks, exact = lb, lb_decks, False
    return {"kind": kind, "total": total, "decks": [list(q) for _, q in decks], "values": [v for v, _ in decks],
            "idx": [T.idx[frozenset(q)] for _, q in decks], "lb": lb, "seed_limit": seed_limit, "kept": len(keep),
            "prune": pinfo, "exact": exact, "seconds": round(time.time() - t0, 1)}


def enum_packs(vals: Sequence[float], rows: Sequence[Sequence[int]], m: int, thr: float, k: int = 5,
               cap: int = 2_000_000, deadline_s: float = 600.0) -> dict[str, Any]:
    """값 내림차순 후보(rows = 구성마다 니케 번호)에서 합 ≥ thr인 겹치지 않는 k덱을 모두 센다.
    상한은 `pack_vals`와 같다: 「남은 후보 앞 r개 값 합」과 「감한 값 상위 r개 + 안 쓴 니케 λ 상위 5r개」 중 작은 쪽.
    cap · 시간에 닿으면 그때까지 센 수(하한)와 complete = False."""
    import heapq
    import numpy as np
    n = len(vals)
    state: dict[str, Any] = {"count": 0, "stop": None, "used": set()}
    if n < k:
        return {"count": 0, "complete": True, "stop": None, "members": []}
    masks = [sum(1 << x for x in r) for r in rows]
    inc = np.array(rows, dtype=np.int64)
    lam = _lag(vals, inc, m, k, thr).tolist()
    red = [vals[j] - sum(lam[x] for x in rows[j]) for j in range(n)]
    lam_order = sorted(range(m), key=lambda x: -lam[x])
    smax = inc.shape[1]
    end = time.monotonic() + deadline_s
    ticks = [0]

    def dfs(L: list[int], used: int, total: float, r: int, path: list[int]) -> None:
        ticks[0] += 1
        if not ticks[0] & 1023 and time.monotonic() > end:
            state["stop"] = "time"
            return
        nL = len(L)
        if nL < r:
            return
        if r == 1:
            for i in L:
                if total + vals[i] < thr:
                    return
                state["count"] += 1
                state["used"].update(path)
                state["used"].add(i)
                if state["count"] >= cap:
                    state["stop"] = "cap"
                    return
            return
        need, lam_top, got = smax * r, 0.0, 0
        for x in lam_order:
            if got == need:
                break
            if not (used >> x) & 1:
                lam_top += lam[x]
                got += 1
        suf = [float("-inf")] * (nL + 1)
        top: list[float] = []
        for p in range(nL - 1, -1, -1):
            x = red[L[p]]
            if len(top) < r:
                heapq.heappush(top, x)
            elif x > top[0]:
                heapq.heapreplace(top, x)
            if len(top) == r:
                suf[p] = sum(top)
        for p in range(nL - r + 1):
            b = total
            for q in range(p, p + r):
                b += vals[L[q]]
            if b < thr or total + suf[p] + lam_top + LAG_SLACK < thr:
                return
            i = L[p]
            mi = masks[i]
            path.append(i)
            dfs([j for j in L[p + 1:] if not masks[j] & mi], used | mi, total + vals[i], r - 1, path)
            path.pop()
            if state["stop"]:
                return

    dfs(list(range(n)), 0, 0.0, k, [])
    return {"count": state["count"], "complete": state["stop"] is None, "stop": state["stop"], "members": sorted(state["used"])}


def landscape(T: Table, kind: str, opt: float, x: float, cap: int = 2_000_000, deadline_s: float = 600.0) -> dict[str, Any]:
    """OPT의 x 이상인 5덱 수와 그 5덱들에 든 구성(가지치기한 후보 위에서 셈 — 상한 < thr 구성은 들 수 없다)."""
    thr = x * opt - 1e-9
    keep, _ = prune(T, kind, thr)
    v = T.values(kind)
    got = enum_packs([v[i] for i in keep], [[T.bit[n] for n in T.cs[i]] for i in keep], len(T.bit), thr,
                     cap=cap, deadline_s=deadline_s)
    return {"x": x, "candidates": len(keep), "count": got["count"], "complete": got["complete"], "stop": got["stop"],
            "comps_in": [keep[j] for j in got["members"]], "keep": keep}


def r_need(T: Table, kind: str, thr: float, k: int = 5, deadline_s: float = 600.0) -> dict[str, Any]:
    """값 상위 K개만 보고도 합 ≥ thr인 겹치지 않는 k덱이 있는 가장 작은 K(= thr 이상 5덱들 중 「가장 낮은 구성 순위」의 최소).
    상한 < thr인 구성은 어느 해에도 못 들므로 후보(keep) 안에서 앞 m개로 이분 탐색한다(`pack_vals` floor)."""
    order = T.sorted_idx(kind)
    rank = {i: r + 1 for r, i in enumerate(order)}
    keep, _ = prune(T, kind, thr - 1e-9)
    keep.sort(key=rank.__getitem__)
    exact = [True]

    def ok(m: int) -> bool:
        try:
            t, d = R9.pack_vals(T.book(kind, keep[:m]), k=k, floor=thr - 1e-7, deadline=time.monotonic() + deadline_s)
        except R9.PackTimeout as e:
            exact[0] = False
            return bool(e.decks) and e.total >= thr - 1e-7
        return bool(d) and t >= thr - 1e-7

    if len(keep) < k or not ok(len(keep)):
        return {"K": None, "candidates": len(keep), "exact": exact[0]}
    lo, hi = k, len(keep)
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return {"K": rank[keep[lo - 1]], "candidates": len(keep), "exact": exact[0]}


def pack_fixed(T: Table, kind: str, squads: Sequence[Sequence[str]], extra: Mapping[frozenset, float] | None = None
               ) -> tuple[float, list[tuple[float, tuple]]]:
    """주어진 스쿼드들(랭커 덱 등)만으로 겹치지 않는 5덱 최고. 값 = max(표 값, extra 값)(풀 밖 스쿼드는 extra만)."""
    v = T.values(kind)
    book: dict[frozenset, tuple[float, tuple]] = {}
    for q in squads:
        c = frozenset(q)
        cands = []
        if c in T.idx and v[T.idx[c]] is not None:
            cands.append(v[T.idx[c]])
        if extra and extra.get(c) is not None:
            cands.append(extra[c])
        if cands and len(c) == 5:
            book[c] = (max(cands), tuple(q))
    return R9.pack_vals(book) if len(book) >= 5 else (0.0, [])


# ---------------------------------------------------------------- 2단계: 배치 순서 다듬기

REFINE_TOP = 2000
REFINE_X = 0.97
REFINE_ROUNDS = 2
REFINE_BATCH = 2000


def ranker_squads(s: int) -> list[list[str]]:
    return [list(q) for q in P41.ranker_sets(s)["squads"]]


def refine_orders(T: Table, i: int) -> list[tuple]:
    """구성 i의 「딜이 달라질 수 있는 순서」 중 아직 안 잰 것(기본 순서 · 2단계 기록의 stage_key는 뺀다)."""
    done = {stage_key(base_order(T.cs[i]))} | set(T.refined.get(i, {}))
    return [o for o in R2.distinct_orders(base_order(T.cs[i]), BURST) if stage_key(o) not in done]


def in_some_pack(T: Table, kind: str, thr: float, deadline_s: float = 600.0) -> dict[str, Any]:
    """합 ≥ thr인 겹치지 않는 5덱에 한 번이라도 드는 구성(정확). 먼저 5덱을 세며 모으고, 셈이 끊기면 남은 후보마다
    「겹치지 않는 4덱으로 thr − v(i) 이상을 채울 수 있나」를 `pack_vals`(floor)로 묻는다."""
    L = landscape(T, kind, thr, 1.0, deadline_s=deadline_s)     # x = 1.0 · opt = thr
    got = set(L["comps_in"])
    if L["complete"]:
        return {"comps": sorted(got), "candidates": len(L["keep"]), "count": L["count"], "complete": True, "exact": True}
    v = T.values(kind)
    keep = L["keep"]
    exact = True
    end = time.monotonic() + deadline_s
    for i in keep:
        if i in got:
            continue
        rest = [j for j in keep if not T.masks[j] & T.masks[i]]
        try:
            tot, d = R9.pack_vals(T.book(kind, rest), k=4, floor=thr - v[i] - 1e-7, deadline=end)
        except R9.PackTimeout:
            got.add(i)                        # 판정 못 함 → 넉넉하게 넣는다(다듬기 대상이 늘 뿐)
            exact = False
            continue
        if d and v[i] + tot >= thr - 1e-7:
            got.add(i)
    return {"comps": sorted(got), "candidates": len(keep), "count": L["count"], "complete": False, "exact": exact}


def cmd_refine(a: argparse.Namespace) -> int:
    """대상 (a) 기본 순서 값 상위 2,000 · (b) OPT의 97% 이상 5덱에 든 구성 전부 · (c) 랭커 상위 40 스쿼드(풀 안)의
    「딜이 달라질 수 있는 순서」를 모두 잰다. 다듬은 값으로 (b)를 다시 구해 새로 든 구성이 있으면 한 번 더(최대 2번)."""
    s = a.season
    f = sdir(s) / "refine.jsonl.gz"
    meta_f = sdir(s) / "refine_meta.json"
    meta = jload(meta_f) or {"season": s, "top": REFINE_TOP, "x": REFINE_X, "rounds": []}
    if meta["rounds"]:
        meta.setdefault("resumed", []).append(len(meta["rounds"]))
    T = Table.load(s)
    targets: dict[int, str] = {}
    for i in T.sorted_idx("base")[:REFINE_TOP]:
        targets.setdefault(i, "a")
    for q in ranker_squads(s):
        if frozenset(q) in T.idx:
            targets.setdefault(T.idx[frozenset(q)], "c")
    with evaluator(a.jobs) as ev:
        ver = ev_version(ev)
        for rnd in range(REFINE_ROUNDS + 1):
            kind = "base" if rnd == 0 else "ref"
            opt = exact_opt(T, kind)
            b = in_some_pack(T, kind, REFINE_X * opt["total"], deadline_s=a.deadline)
            new = [i for i in b["comps"] if i not in targets]
            for i in new:
                targets[i] = "b" if rnd == 0 else f"b{rnd}"
            todo = [(i, o) for i in sorted(targets, key=lambda i: (-T.base[i], i)) for o in refine_orders(T, i)]
            info = {"round": rnd, "kind": kind, "opt": opt["total"], "opt_exact": opt["exact"], "opt_kept": opt["kept"],
                    "b_comps": len(b["comps"]), "b_new": len(new), "b_exact": b["exact"], "b_count": b["count"],
                    "b_complete": b["complete"], "targets": collections_count(targets.values()), "orders": len(todo)}
            if rnd > 0 and not new:
                info["stop"] = "97% 안에 새로 든 구성 없음"
            if todo:
                t0, n0, errs = time.time(), ev.sim_count, 0
                for b0 in range(0, len(todo), REFINE_BATCH):     # 조각마다 써서 끊겨도 잰 순서는 남는다(다시 돌면 건너뜀)
                    part = todo[b0:b0 + REFINE_BATCH]
                    got = run_orders(s, [o for _, o in part], ev)
                    with gzip.open(f, "at", encoding="utf-8") as fh:
                        for (i, o), (v, m) in zip(part, got):
                            fh.write(json.dumps({"i": i, "order": list(o), "value": v, "members": m, "round": rnd,
                                                 "why": targets[i]}, ensure_ascii=False) + "\n")
                            if v is None:
                                errs += 1
                                continue
                            T.refined.setdefault(i, {})[stage_key(o)] = (v, tuple(o))
                            if T.ref[i] is None or v > T.ref[i]:
                                T.ref[i], T.best_order[i] = v, tuple(o)
                    print(f"S{s} 다듬기 {rnd}회 {min(b0 + REFINE_BATCH, len(todo))}/{len(todo)}", flush=True)
                info.update(sims=ev.sim_count - n0, seconds=round(time.time() - t0, 1), evaluator=ver, errors=errs)
            else:
                info["sims"] = 0
            meta["rounds"].append(info)
            jdump(meta_f, meta)
            print(json.dumps(info, ensure_ascii=False), flush=True)
            if "stop" in info:
                break
    return 0


def collections_count(xs: Any) -> dict[str, int]:
    import collections
    return dict(collections.Counter(xs))


# ---------------------------------------------------------------- 관찰: 자리 순서 전부(120가지) — stage_key 가정 점검

PERM_TOP = 30


def load_perm(s: int) -> dict[int, dict[tuple, float]]:
    f = sdir(s) / "perm.jsonl.gz"
    out: dict[int, dict[tuple, float]] = {}
    if f.exists():
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["value"] is not None:
                    out.setdefault(r["i"], {})[tuple(r["order"])] = r["value"]
    return out


def perm_targets(s: int, T: Table) -> dict[int, str]:
    """OPT(다듬은 값) 5덱 · 랭커 스쿼드 최선 5덱 · 우리 A 5덱 · 다듬은 값 상위 PERM_TOP."""
    pk = jload(sdir(s) / "pack.json")
    e36 = exp36_values(s)
    out: dict[int, str] = {}
    for i in pk["ref"]["opt"]["idx"]:
        out.setdefault(i, "opt")
    rs = P41.ranker_sets(s)
    _, rb = pack_fixed(T, "ref", [q for v in rs.values() for q in v], e36["rankers"])
    for _, q in rb:
        if frozenset(q) in T.idx:
            out.setdefault(T.idx[frozenset(q)], "ranker_best")
    for q in e36["A_decks"]:
        if frozenset(q) in T.idx:
            out.setdefault(T.idx[frozenset(q)], "A")
    for i in T.sorted_idx("ref")[:PERM_TOP]:
        out.setdefault(i, "top")
    return out


def cmd_perm(a: argparse.Namespace) -> int:
    """관찰(판단에 안 씀): 대상 구성의 자리 순서 120가지를 모두 잰다(표 · 2단계에서 잰 순서는 다시 재지 않는다)."""
    from itertools import permutations
    s = a.season
    T = Table.load(s)
    done = load_perm(s)
    tg = perm_targets(s, T)
    measured: dict[int, set] = {i: {tuple(o) for _, o in T.refined.get(i, {}).values()} | {base_order(T.cs[i])} for i in tg}
    todo = [(i, o) for i in sorted(tg) for o in permutations(base_order(T.cs[i]))
            if o not in measured[i] and o not in done.get(i, {})]
    t0 = time.time()
    with evaluator(a.jobs) as ev:
        n0 = ev.sim_count
        for b0 in range(0, len(todo), REFINE_BATCH):
            part = todo[b0:b0 + REFINE_BATCH]
            got = run_orders(s, [o for _, o in part], ev)
            with gzip.open(sdir(s) / "perm.jsonl.gz", "at", encoding="utf-8") as fh:
                for (i, o), (v, _) in zip(part, got):
                    fh.write(json.dumps({"i": i, "order": list(o), "value": v, "why": tg[i]}, ensure_ascii=False) + "\n")
            print(f"S{s} 자리 순서 {min(b0 + REFINE_BATCH, len(todo))}/{len(todo)}", flush=True)
        jdump(sdir(s) / "perm_meta.json", {"season": s, "targets": len(tg), "sims": ev.sim_count - n0,
                                           "seconds": round(time.time() - t0, 1), "evaluator": ev_version(ev)})
    return 0


def perm_summary(s: int, T: Table) -> dict[str, Any] | None:
    """자리 순서 전부의 최고 ÷ 2단계 값(stage_key 대표 순서 최고) − 1, 그 값으로 바꿔 다시 묶은 5덱(OPT의 하한)."""
    P = load_perm(s)
    if not P:
        return None
    tg = perm_targets(s, T)
    gains, vals = {}, list(T.ref)
    for i in tg:
        allv = list(P.get(i, {}).values()) + [v for v, _ in T.refined.get(i, {}).values()] + [T.base[i]]
        best = max(x for x in allv if x is not None)
        gains[i] = best / T.ref[i] - 1
        vals[i] = best
    T2 = Table(s, T.cs, vals, None, sorted(T.bit))
    opt2 = exact_opt(T2, "base")
    xs = sorted(gains.values())
    e36 = exp36_values(s)
    rs = P41.ranker_sets(s)
    rb2, _ = pack_fixed(T2, "base", [q for v in rs.values() for q in v], e36["rankers"])
    return {"comps": len(tg), "gain_median": median(xs), "gain_max": xs[-1], "gain_ge_1pct": sum(x >= 0.01 for x in xs),
            "by_why": {w: median([gains[i] for i in tg if tg[i] == w]) for w in sorted(set(tg.values()))},
            "opt_perm_lb": opt2["total"], "opt_perm_decks": opt2["decks"], "opt_perm_exact": opt2["exact"],
            "A_perm": five_sum(T2, "base", e36["A_decks"]), "ranker_best_perm": rb2,
            "miss_perm": opt2["total"] / e36["A_total"] - 1, "ranker_ratio_perm": rb2 / opt2["total"]}


# ---------------------------------------------------------------- 관찰: 다듬기 밖 표본 — 다듬지 않은 구성이 다듬으면 얼마나 오르나

SAMPLE_N = 500
SAMPLE_RANK = 50000


def cmd_sample(a: argparse.Namespace) -> int:
    """관찰(판단에 안 씀): 2단계에서 다듬지 않은 구성 중 기본 순서 값 상위 SAMPLE_RANK 안에서 무작위 SAMPLE_N개의
    「딜이 달라질 수 있는 순서」(2단계와 같은 순서 공간)를 모두 잰다 — 다듬기 밖에 숨은 값의 크기."""
    s = a.season
    f = sdir(s) / "sample.jsonl.gz"
    if f.exists():
        return 0
    T = Table.load(s)
    pool_ = [i for i in T.sorted_idx("base")[:SAMPLE_RANK] if i not in T.refined]
    pick = sorted(random.Random(f"exp41-sample-{s}").sample(pool_, min(SAMPLE_N, len(pool_))))
    todo = [(i, o) for i in pick for o in refine_orders(T, i)]
    t0 = time.time()
    with evaluator(a.jobs) as ev:
        n0 = ev.sim_count
        got = run_orders(s, [o for _, o in todo], ev)
        tmp = f.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            for (i, o), (v, _) in zip(todo, got):
                fh.write(json.dumps({"i": i, "order": list(o), "value": v}, ensure_ascii=False) + "\n")
        tmp.rename(f)
        jdump(sdir(s) / "sample_meta.json", {"season": s, "comps": len(pick), "orders": len(todo), "sims": ev.sim_count - n0,
                                             "seconds": round(time.time() - t0, 1), "evaluator": ev_version(ev)})
    return 0


def sample_summary(s: int, T: Table) -> dict[str, Any] | None:
    f = sdir(s) / "sample.jsonl.gz"
    if not f.exists():
        return None
    best: dict[int, float] = {}
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["value"] is not None:
                best[r["i"]] = max(best.get(r["i"], T.base[r["i"]]), r["value"])
    gains = sorted(best[i] / T.base[i] - 1 for i in best)
    rb = T.ranks("base")
    refv = sorted((x for x in T.ref if x is not None), reverse=True)
    import bisect
    neg = [-x for x in refv]
    new_rank = {i: bisect.bisect_left(neg, -best[i]) + 1 for i in best}
    q = lambda p: gains[min(len(gains) - 1, int(p * (len(gains) - 1)))]  # noqa: E731
    return {"comps": len(best), "gain_median": median(gains), "gain_p90": q(0.9), "gain_p99": q(0.99), "gain_max": gains[-1],
            "gain_ge_5pct": sum(g >= 0.05 for g in gains), "gain_ge_10pct": sum(g >= 0.10 for g in gains),
            "rank_jump_into_top2000": sum(1 for i in best if rb[i] > REFINE_TOP and new_rank[i] <= REFINE_TOP),
            "rank_base_median": median([rb[i] for i in best])}


# ---------------------------------------------------------------- 3단계: 답안지 묶기 · 채점(시뮬 0)

LAND_X = (0.99, 0.97)
RNEED_X = (1.0, 0.99, 0.97)
CLASS_LOW = 0.97
CLASS_MAX = 30


def exp36_values(s: int) -> dict[str, Any]:
    """실험 36 사전 값: 우리 A(maps.json nocore|A 최선) · 랭커 덱(rankers.json 코어 없음, 랭커 순서)."""
    m = jload(EXP36_LOG / f"S{s}" / "maps.json")["nocore|A"]
    rk = jload(EXP36_LOG / f"S{s}" / "rankers.json")["squads"]
    return {"A_total": m["best"], "A_decks": m["reps"][0]["decks"],
            "rankers": {frozenset(k.split(",")): v["nocore"] for k, v in rk.items() if v.get("nocore") is not None}}


def five_sum(T: Table, kind: str, decks: Sequence[Sequence[str]], extra: Mapping[frozenset, float] | None = None) -> float | None:
    """5덱의 합 — 구성마다 max(표 값, extra). 하나라도 값이 없으면 None."""
    v = T.values(kind)
    tot = 0.0
    for q in decks:
        c = frozenset(q)
        xs = [v[T.idx[c]]] if c in T.idx and v[T.idx[c]] is not None else []
        if extra and extra.get(c) is not None:
            xs.append(extra[c])
        if not xs:
            return None
        tot += max(xs)
    return tot


def cmd_pack(a: argparse.Namespace) -> int:
    s = a.season
    T = Table.load(s)
    t0 = time.time()
    out: dict[str, Any] = {"season": s, "refined_comps": len(T.refined)}
    for kind in ("base", "ref"):
        opt = exact_opt(T, kind, deadline_s=a.deadline)
        rk = T.ranks(kind)
        opt["ranks"] = [rk[i] for i in opt["idx"]]
        opt["members"] = [T.order_of(kind, i) for i in opt["idx"]]
        land = {}
        for x in LAND_X:
            L = landscape(T, kind, opt["total"], x, cap=a.cap, deadline_s=a.deadline)
            land[str(x)] = {k: L[k] for k in ("candidates", "count", "complete", "stop")} | {"comps_in": len(L["comps_in"])}
            if x == min(LAND_X):
                low_keep = L["keep"]
        # 큰 분류(실험 30 class_map, J ≤ 0.2): 97% 후보 위에서
        cm = R30.class_map(T.book(kind, low_keep), max_reps=CLASS_MAX, low=CLASS_LOW)
        classes = {str(x): sum(1 for r in cm["reps"] if not r.get("below") and r["total"] >= x * opt["total"] - 1e-9) for x in LAND_X}
        rn = {str(x): r_need(T, kind, x * opt["total"], deadline_s=a.deadline) for x in RNEED_X}
        out[kind] = {"opt": opt, "landscape": land, "classes": classes, "class_reps": cm["reps"], "class_exact": cm["exact"],
                     "r_need": rn}
        print(json.dumps({"season": s, "kind": kind, "opt": opt["total"], "exact": opt["exact"], "kept": opt["kept"],
                          "ranks": opt["ranks"], "land": {k: (x["count"], x["complete"]) for k, x in land.items()},
                          "classes": classes, "r_need": rn}, ensure_ascii=False), flush=True)
    out["seconds"] = round(time.time() - t0, 1)
    jdump(sdir(s) / "pack.json", out)
    return 0


# ---------------------------------------------------------------- 4단계: 지금 절차 재생(표 조회 평가기, 시뮬 0)

REPLAY_SEEDS = (0, 1, 2, 3)
REPLAY_BUDGET = run31.SEED_BUDGET     # 12,500
REPLAY_GRID = 500


class TableEvaluator:
    """평가기 대신 표를 본다. 구성이 표에 없으면 오류(KeyError). 순서는 stage_key로 찾고, 잰 적 없는 순서는 기본 순서 값으로 답한다."""

    def __init__(self, T: Table):
        from nikke_opt.evaluator import EvalResult
        self.T, self._R = T, EvalResult
        self.sim_count, self.cache_hits = 0, 0
        self.version = {"repo": "table41", "commit": f"S{T.s}"}
        self.exact, self.fallback = 0, 0
        self.base_key = {}

    def evaluate(self, requests: Sequence[Any]) -> list[Any]:
        out = []
        for r in requests:
            c = frozenset(r.squad)
            i = self.T.idx[c]                      # 표 밖 구성 → KeyError(풀을 줄였으니 생기지 않아야 한다)
            k = stage_key(r.squad)
            got = self.T.refined.get(i, {}).get(k)
            if got is not None:
                v = got[0]
                self.exact += 1
            elif k == stage_key(base_order(self.T.cs[i])):
                v = self.T.base[i]
                self.exact += 1
            else:
                v = self.T.base[i]
                self.fallback += 1
            self.sim_count += 1
            raw = {"total_damage": None, "error": {"message": "표 값 없음"}} if v is None else {"total_damage": round(v * E8)}
            out.append(self._R(None if v is None else round(v * E8), raw, False))
        return out

    def submit(self, requests: Sequence[Any]) -> list[Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


def replay_account(s: int, seed: int) -> Any:
    names = pool(s)
    sc = dict(R10.pre_scenario(), id=run31.account_id(s, seed), name=f"S{s} 답안지 풀 {len(names)}명",
              missing=[n for n in R10.P177 if n not in set(names)])
    acct = R10.Account10(sc, pool=177, rankerless=True)
    assert set(acct.names) == set(names)
    acct.options = options(s)
    return acct


def grid_of(history: Sequence[Mapping[str, Any]], opt: float, step: int = REPLAY_GRID, budget: int = REPLAY_BUDGET) -> list[list]:
    """평가 수 step마다 그때까지의 정확 묶음 합 ÷ OPT(라운드 기록 중 그 평가 수 이하 마지막 값)."""
    out = []
    for e in range(step, budget + step, step):
        xs = [h["pack"] for h in history if h["evals"] <= e]
        out.append([e, xs[-1] / opt if xs else None])
    return out


def first_reach(history: Sequence[Mapping[str, Any]], opt: float, x: float) -> int | None:
    for h in history:
        if h["pack"] >= x * opt - 1e-9:
            return h["evals"]
    return None


def cmd_replay(a: argparse.Namespace) -> int:
    s = a.season
    T = Table.load(s)
    pk = jload(sdir(s) / "pack.json")
    if not pk:
        raise RuntimeError(f"S{s}: 먼저 pack")
    opt = pk["ref"]["opt"]["total"]
    seeds = REPLAY_SEEDS if a.seed is None else (a.seed,)
    for k in seeds:
        f = sdir(s) / f"replay_s{k}.json"
        if f.exists() and not a.force:
            continue
        ev = TableEvaluator(T)
        acct = replay_account(s, k)
        t0 = time.time()
        summ, recs, sess = R10.run_method(acct, "G+E", REPLAY_BUDGET, ev, pool=177)
        hist = summ["history"]
        fin = summ["final"]
        out = {"season": s, "seed": k, "account": acct.id, "budget": REPLAY_BUDGET, "evals": summ["evals"], "opt": opt,
               "final": fin, "final_ratio": fin["total"] / opt, "pre_order_ratio": summ["pre_order"]["pack"] / opt,
               "reach": {str(x): first_reach(hist, opt, x) for x in (0.99, 0.97)},
               "grid": grid_of(hist, opt), "history": hist, "kicks": summ["kicks"],
               "lookups": {"exact": ev.exact, "fallback": ev.fallback}, "errors": summ["errors"],
               "comps_seen": len(sess.book.best), "seconds": round(time.time() - t0, 1)}
        jdump(f, out)
        print(json.dumps({k2: out[k2] for k2 in ("season", "seed", "evals", "final_ratio", "reach", "lookups", "seconds")},
                         ensure_ascii=False), flush=True)
    return 0


# ---------------------------------------------------------------- 분석(시뮬 0) → analysis.json · results.md

# 판단 기준(README §판단 기준 — 2026-11-04 사용자 확정)
MISS_MIN = 0.01        # 1: OPT ÷ 우리 A − 1 ≥ 1%
RANKER_MIN = 0.99      # 2: 랭커 스쿼드 최선 ÷ OPT ≥ 99%
RNEED_NEAR, RNEED_FAR = 40, 500   # 3: R_need(99%) ≤ 40 · 40 < · ≤ 500 · > 500
REPLAY_X, REPLAY_MIN = 0.99, 3    # 4: 재생 12,500에서 OPT의 99% 도달 시드 ≥ 3/4
RHO_MIN, LOW_RATIO, LOW_MAX = 0.6, 1.4, 2   # 5: 실전 ρ < 0.6 또는 1.4배 낮은 덱 ≥ 2 → 계산기 의심


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """평균 순위 스피어만(실험 32 r0 `spearman`과 같은 계산)."""
    def rank(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
                j += 1
            for q in range(i, j + 1):
                r[o[q]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(a) < 3:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def median(xs: Sequence[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def members_of(s: int, T: Table, kind: str, idxs: Sequence[int]) -> dict[int, list]:
    """구성마다 그 값의 배치 순서와 니케별 딜 [[이름, 딜], …]."""
    want = {i: T.order_of(kind, i) for i in idxs}
    out: dict[int, list] = {}
    base_need = {i for i, o in want.items() if tuple(o) == base_order(T.cs[i])}
    if base_need:
        for i, _, m in iter_table(s):
            if i in base_need and m is not None:
                out[i] = [[n, x] for n, x in zip(base_order(T.cs[i]), m)]
    f = sdir(s) / "refine.jsonl.gz"
    if f.exists():
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r["i"] in want and tuple(r["order"]) == tuple(want[r["i"]]) and r["members"]:
                    out[r["i"]] = [[n, x] for n, x in zip(r["order"], r["members"])]
    return out


def real_rows(s: int, T: Table) -> list[dict[str, Any]]:
    """실전 덱(랭커 10명 이상)의 실전 중앙 딜과 표 값(다듬은 값)."""
    rows = []
    for x in P41.real_decks(s):
        c = frozenset(x["deck"].split(","))
        if c in T.idx and T.ref[T.idx[c]] is not None:
            rows.append({"deck": x["deck"], "n": x["n"], "real": x["real"], "calc": T.ref[T.idx[c]],
                         "rank": None})
    if rows:
        rk = T.ranks("ref")
        for r in rows:
            r["rank"] = rk[T.idx[frozenset(r["deck"].split(","))]]
        sc = median([r["real"] / r["calc"] for r in rows])
        for r in rows:
            r["under"] = r["real"] / r["calc"] / sc
    return rows


def analyze_season(s: int) -> dict[str, Any]:
    from nikke_opt import similarity as SIM
    T = Table.load(s)
    pk = jload(sdir(s) / "pack.json")
    e36 = exp36_values(s)
    opt = pk["ref"]["opt"]["total"]
    rk_ref, rk_base = T.ranks("ref"), T.ranks("base")
    rsets = P41.ranker_sets(s)
    extra = e36["rankers"]
    # 1 · 2: 우리 A · 랭커 대 OPT
    a_tab = five_sum(T, "ref", e36["A_decks"])
    all_rk = [q for v in rsets.values() for q in v]
    rk_best, rk_best_decks = pack_fixed(T, "ref", all_rk, extra)
    in_tab = [q for q in all_rk if frozenset(q) in T.idx]
    rk_in, _ = pack_fixed(T, "ref", in_tab, extra)          # 표 공간(풀 안 · 구조 규칙 통과)만, 랭커 순서 값 포함
    rk_in_tab, _ = pack_fixed(T, "ref", in_tab, None)       # 표 공간만, 표 값만
    pset = set(pool(s))
    outside = {frozenset(q) for q in all_rk if frozenset(q) not in T.idx}
    out_struct = sum(1 for c in outside if c <= pset and not P41.passes(sorted(c)))
    out_pool = sum(1 for c in outside if not c <= pset)
    used_out = [list(q) for _, q in rk_best_decks if frozenset(q) not in T.idx]
    top5 = five_sum(T, "ref", rsets["top_five"], extra)
    rank1 = five_sum(T, "ref", rsets["rank1"], extra)
    top5_36 = sum(extra[frozenset(q)] for q in rsets["top_five"]) if all(frozenset(q) in extra for q in rsets["top_five"]) else None
    rank1_36 = sum(extra[frozenset(q)] for q in rsets["rank1"]) if all(frozenset(q) in extra for q in rsets["rank1"]) else None
    # 3: R_need
    rn = pk["ref"]["r_need"]
    rn99 = rn["0.99"]["K"]
    # 4: 재생
    reps = [jload(sdir(s) / f"replay_s{k}.json") for k in REPLAY_SEEDS]
    reps = [r for r in reps if r]
    reach = [r for r in reps if r["final_ratio"] >= REPLAY_X - 1e-12]
    # 5: 실전
    rows = real_rows(s, T)
    rho = spearman([r["real"] for r in rows], [r["calc"] for r in rows])
    low = [r for r in rows if r["under"] >= LOW_RATIO]
    # 관찰
    opt_idx = pk["ref"]["opt"]["idx"]
    mem = members_of(s, T, "ref", opt_idx)
    gains = [T.ref[i] / T.base[i] - 1 for i in T.refined if T.base[i]]
    a_idx = [T.idx.get(frozenset(q)) for q in e36["A_decks"]]
    sims = {"table": sum(p["sims"] for p in (jload(sdir(s) / "table_meta.json") or {}).get("parts", {}).values()),
            "refine": sum(r.get("sims", 0) for r in (jload(sdir(s) / "refine_meta.json") or {}).get("rounds", []))}
    j = lambda a, b: SIM.pair_jaccard(a, b)  # noqa: E731
    opt_decks = pk["ref"]["opt"]["decks"]
    q = {
        "1_miss": {"value": opt / e36["A_total"] - 1, "hit": opt / e36["A_total"] - 1 >= MISS_MIN},
        "2_ranker": {"value": rk_best / opt, "hit": rk_best / opt >= RANKER_MIN},
        "3_r_need": {"value": rn99, "band": None if rn99 is None else
                     ("≤40" if rn99 <= RNEED_NEAR else "41~500" if rn99 <= RNEED_FAR else ">500")},
        "4_replay": {"value": len(reach), "of": len(reps), "hit": len(reach) >= REPLAY_MIN if len(reps) == len(REPLAY_SEEDS) else None},
        "5_calc": {"rho": rho, "low": len(low), "decks": len(rows),
                   "hit": None if rho is None else (rho < RHO_MIN or len(low) >= LOW_MAX)},
    }
    return {
        "season": s, "boss": POOLS[str(s)]["boss"], "pool": len(pool(s)), "comps": len(T.cs), "sims": sims,
        "opt": opt, "opt_exact": pk["ref"]["opt"]["exact"], "opt_base": pk["base"]["opt"]["total"],
        "opt_decks": opt_decks, "opt_ranks_ref": [rk_ref[i] for i in opt_idx], "opt_ranks_base": [rk_base[i] for i in opt_idx],
        "opt_members": [mem.get(i) for i in opt_idx],
        "A_exp36": e36["A_total"], "A_table": a_tab, "A_ranks_ref": [rk_ref.get(i) if i is not None else None for i in a_idx],
        "ranker_best": rk_best, "ranker_best_decks": [list(x) for _, x in rk_best_decks],
        "ranker_best_in_table": rk_in, "ranker_best_in_table_tablevals": rk_in_tab,
        "ranker_outside": {"structure": out_struct, "pool": out_pool, "in_best": used_out},
        "top_five": top5, "top_five_exp36": top5_36, "rank1": rank1, "rank1_exp36": rank1_36,
        "J_top_five": j(opt_decks, rsets["top_five"]), "J_rank1": j(opt_decks, rsets["rank1"]),
        "J_A": j(opt_decks, e36["A_decks"]),
        "r_need": {"ref": pk["ref"]["r_need"], "base": pk["base"]["r_need"]},
        "landscape": pk["ref"]["landscape"], "classes": pk["ref"]["classes"],
        "replay": [{k2: r[k2] for k2 in ("seed", "evals", "final_ratio", "pre_order_ratio", "reach", "lookups", "grid")} for r in reps],
        "real": {"rho": rho, "low": [[r["deck"], round(r["under"], 3), r["n"]] for r in low], "decks": len(rows),
                 "rows": rows},
        "refine_gain": {"comps": len(gains), "median": median(gains), "p90": sorted(gains)[int(0.9 * (len(gains) - 1))] if gains else None,
                        "max": max(gains) if gains else None},
        "ranker_squad_ranks_ref": sorted(rk_ref[T.idx[frozenset(x)]] for x in rsets["squads"] if frozenset(x) in T.idx),
        "ranker_order_over_table": sum(1 for c, x in extra.items() if c in T.idx and x > T.ref[T.idx[c]] + 1e-6),
        "ranker_in_table": sum(1 for c in extra if c in T.idx),
        "perm": perm_summary(s, T),
        "sample": sample_summary(s, T),
        "questions": q,
    }


def fb_share(x: Mapping[str, Any]) -> str:
    lk = x["lookups"]
    return f"{lk['fallback'] / max(1, lk['fallback'] + lk['exact']):.0%}"


def pct(x: float | None, d: int = 2) -> str:
    return "—" if x is None else f"{100 * x:.{d}f}%"


def write_md(rows: Sequence[Mapping[str, Any]]) -> str:
    L = ["# 실험 41 결과 — 답안지(작은 풀 전수 계산)", "",
         "`run41.py analyze`가 만든다. 값 = 기본 레이어 1시뮬 사전 값(코어 없음, 카메라 재장전 옵션 켬), OPT = 다듬은 값으로 정확히 묶은 5덱 합.", "",
         "## 판단 표(사전 등록 기준)", "",
         "| 시즌 | 1 놓친 몫 OPT ÷ 우리 A − 1 (≥ 1%) | 2 랭커 스쿼드 최선 ÷ OPT (≥ 99%) | 3 R_need(99%) | 4 재생 99% 도달 (≥ 3/4) | 5 실전 ρ · 1.4배 낮은 덱 |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        q = r["questions"]
        yn = lambda b: "—" if b is None else ("예" if b else "아니오")  # noqa: E731
        c5 = q["5_calc"]
        rho = "—" if c5["rho"] is None else f"{c5['rho']:.2f}"
        L.append(f"| S{r['season']} | {pct(q['1_miss']['value'])} ({yn(q['1_miss']['hit'])}) | "
                 f"{pct(q['2_ranker']['value'])} ({yn(q['2_ranker']['hit'])}) | "
                 f"{q['3_r_need']['value']} ({q['3_r_need']['band']}) | {q['4_replay']['value']}/{q['4_replay']['of']} ({yn(q['4_replay']['hit'])}) | "
                 f"{rho} · {c5['low']}/{c5['decks']} ({'의심' if c5['hit'] else '아님'}) |")
    L += ["", "## 값", "", "| 시즌 | 풀 · 구성 | OPT(억) | 증명 | 우리 A(실험 36) | 우리 A(표 값) | 랭커 스쿼드 최선 | 대표 5덱 | 1위 5덱 | J(OPT, 대표) | J(OPT, A) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        o = r["opt"]
        L.append(f"| S{r['season']} | {r['pool']} · {r['comps']:,} | {o:.2f} | {'정확' if r['opt_exact'] else '미증명'} | "
                 f"{r['A_exp36']:.2f} ({pct(r['A_exp36'] / o, 1)}) | {r['A_table']:.2f} ({pct(r['A_table'] / o, 1)}) | "
                 f"{r['ranker_best']:.2f} ({pct(r['ranker_best'] / o, 1)}) | {r['top_five']:.2f} ({pct(r['top_five'] / o, 1)}) | "
                 f"{r['rank1']:.2f} ({pct(r['rank1'] / o, 1)}) | {r['J_top_five']:.2f} | {r['J_A']:.2f} |")
    L += ["", "랭커 스쿼드 최선의 분해 — 표 공간(풀 안 · 구조 규칙 통과) 밖 스쿼드와 랭커 순서 값을 빼면:", "",
          "| 시즌 | 랭커 스쿼드 최선(전부) | 표 공간만(랭커 순서 포함) | 표 공간만 · 표 값만 | 표 밖 랭커 스쿼드: 구조 규칙 밖 · 풀 밖 | 최선에 든 표 밖 스쿼드 |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        o, ro = r["opt"], r["ranker_outside"]
        L.append(f"| S{r['season']} | {pct(r['ranker_best'] / o, 1)} | {pct(r['ranker_best_in_table'] / o, 1)} | "
                 f"{pct(r['ranker_best_in_table_tablevals'] / o, 1)} | {ro['structure']} · {ro['pool']} | "
                 f"{'; '.join(' · '.join(q) for q in ro['in_best']) or '—'} |")
    L += ["", "## 순위 · 경치", "", "| 시즌 | OPT 스쿼드 순위(다듬은 값) | (기본 순서 값) | R_need 100 · 99 · 97% | 99% · 97% 5덱 수 | 큰 분류 99 · 97% | 우리 A 스쿼드 순위 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        rn = r["r_need"]["ref"]
        ld = r["landscape"]
        cnt = lambda x: f"{ld[x]['count']:,}" + ("" if ld[x]["complete"] else "+")  # noqa: E731
        L.append(f"| S{r['season']} | {sorted(r['opt_ranks_ref'])} | {sorted(r['opt_ranks_base'])} | "
                 f"{rn['1.0']['K']} · {rn['0.99']['K']} · {rn['0.97']['K']} | {cnt('0.99')} · {cnt('0.97')} | "
                 f"{r['classes']['0.99']} · {r['classes']['0.97']} | {sorted(x for x in r['A_ranks_ref'] if x)} |")
    L += ["", "## 재생(지금 절차 G+E, 표 조회 · 시드 4 × 12,500)", "", "| 시즌 | 시드별 12,500 ÷ OPT | 99% 첫 도달 | 97% 첫 도달 | 표에 없는 순서(기본 값으로 답함) |", "|---|---|---|---|---|"]
    for r in rows:
        rp = r["replay"]
        L.append(f"| S{r['season']} | {' · '.join(pct(x['final_ratio'], 1) for x in rp)} | "
                 f"{' · '.join(str(x['reach']['0.99']) for x in rp)} | {' · '.join(str(x['reach']['0.97']) for x in rp)} | "
                 f"{' · '.join(fb_share(x) for x in rp)} |")
    L += ["", "## 관찰: 자리 순서 120가지(stage_key 가정 점검)", "",
          "2단계 · 지금 절차의 순서 다듬기는 「단계 안 순서(stage_key)가 같으면 값이 같다」고 보고 stage_key마다 한 순서만 잰다. "
          "지금 평가기에서는 자리 순서로도 값이 달라서, 대상 구성(OPT · 랭커 최선 · 우리 A 5덱 · 상위 30)의 120가지를 모두 쟀다. "
          "그 값으로 바꿔 다시 묶은 합은 자리 순서까지 본 OPT의 **하한**이다(다른 구성은 그대로).", "",
          "| 시즌 | 랭커 순서 > 표 최고(랭커 스쿼드) | 대상 | 이득 중앙 · 최대 · ≥1% | OPT 하한(억) | ÷ OPT − 1 | 놓친 몫(하한 기준) | 랭커 최선 ÷ 하한 |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        p = r.get("perm")
        if not p:
            continue
        L.append(f"| S{r['season']} | {r['ranker_order_over_table']}/{r['ranker_in_table']} | {p['comps']} | "
                 f"{pct(p['gain_median'], 1)} · {pct(p['gain_max'], 1)} · {p['gain_ge_1pct']} | {p['opt_perm_lb']:.2f} | "
                 f"{pct(p['opt_perm_lb'] / r['opt'] - 1)} | {pct(p['miss_perm'])} | {pct(p['ranker_ratio_perm'], 1)} |")
    L += ["", "## 관찰: 다듬기 밖 표본(2단계에서 다듬지 않은 구성, 기본 순서 값 상위 5만 안 무작위 500)", "",
          "| 시즌 | 표본 | 기본 순위 중앙 | 다듬기 이득 중앙 · 90% · 99% · 최대 | ≥ 5% · ≥ 10% | 다듬으면 상위 2,000 안으로 |",
          "|---|---|---|---|---|---|"]
    for r in rows:
        p = r.get("sample")
        if not p:
            continue
        L.append(f"| S{r['season']} | {p['comps']} | {p['rank_base_median']:,.0f} | {pct(p['gain_median'], 1)} · {pct(p['gain_p90'], 1)} · "
                 f"{pct(p['gain_p99'], 1)} · {pct(p['gain_max'], 1)} | {p['gain_ge_5pct']} · {p['gain_ge_10pct']} | {p['rank_jump_into_top2000']} |")
    L += ["", "## OPT 5덱(다듬은 값)", ""]
    for r in rows:
        L.append(f"- **S{r['season']}** OPT {r['opt']:.2f}억:")
        for d, m, rk in zip(r["opt_decks"], r["opt_members"], r["opt_ranks_ref"]):
            tot = sum(x for _, x in m) if m else None
            body = " · ".join(f"{n} {x:.1f}" for n, x in m) if m else " · ".join(d)
            L.append(f"  - {'' if tot is None else f'{tot:.2f}억 '}(순위 {rk}) {body}")
    L += ["", "## 시뮬", "", "| 시즌 | 1단계 | 2단계 |", "|---|---|---|"]
    for r in rows:
        L.append(f"| S{r['season']} | {r['sims']['table']:,} | {r['sims']['refine']:,} |")
    return "\n".join(L) + "\n"


def cmd_analyze(a: argparse.Namespace) -> int:
    seasons = [int(x) for x in str(a.season).split(",")] if a.season else list(SEASONS)
    rows = [analyze_season(s) for s in seasons]
    jdump(HERE / "analysis.json", {"seasons": rows})
    (HERE / "results.md").write_text(write_md(rows), encoding="utf-8")
    print((HERE / "results.md").read_text(encoding="utf-8"))
    return 0


# ---------------------------------------------------------------- 명령

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--season", default="36,39,42")
    c.add_argument("--n", type=int, default=300)
    c.add_argument("--jobs", type=int, default=4)
    t = sub.add_parser("table")
    t.add_argument("--season", type=int, required=True)
    t.add_argument("--jobs", type=int, default=4)
    t.add_argument("--limit", type=int, default=None, help="이번에 돌릴 조각 수 상한")
    r = sub.add_parser("refine")
    r.add_argument("--season", type=int, required=True)
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--deadline", type=float, default=900.0, help="묶기 · 셈 하나의 제한 시간(초)")
    k = sub.add_parser("pack")
    k.add_argument("--season", type=int, required=True)
    k.add_argument("--cap", type=int, default=2_000_000, help="5덱 셈 상한")
    k.add_argument("--deadline", type=float, default=900.0)
    y = sub.add_parser("replay")
    y.add_argument("--season", type=int, required=True)
    y.add_argument("--seed", type=int, default=None)
    y.add_argument("--force", action="store_true")
    q = sub.add_parser("perm")
    q.add_argument("--season", type=int, required=True)
    q.add_argument("--jobs", type=int, default=4)
    m = sub.add_parser("sample")
    m.add_argument("--season", type=int, required=True)
    m.add_argument("--jobs", type=int, default=4)
    n = sub.add_parser("analyze")
    n.add_argument("--season", default=None)
    a = p.parse_args(argv)
    return {"check": cmd_check, "table": cmd_table, "refine": cmd_refine, "pack": cmd_pack, "replay": cmd_replay,
            "perm": cmd_perm, "sample": cmd_sample, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
