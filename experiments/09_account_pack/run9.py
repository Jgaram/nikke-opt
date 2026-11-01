"""실험 9 — 계정별 5덱 조립 기법 비교 실행기 (README §비교 기법 · §컨트롤 후처리).

    source .cache/evaluators.env && python experiments/09_account_pack/run9.py search --set dev --out <dir> [--methods L0,L0k,L1,L2]
        [--budgets 300,800,2000] [--only d1,d2] [--workers 4]
    source .cache/evaluators.env && python experiments/09_account_pack/run9.py post --runs <dir> --out <dir2> [--top 5] [--only ...]

- `search`: (시나리오, 기법, 예산)마다 `<dir>/<sid>_<기법>_<예산>.json`(요약)과 `.jsonl.gz`(평가한 스쿼드 전부)를 쓴다.
  이미 있는 실행은 건너뛴다. 평가는 기본 레이어(운용 없음) + 시나리오 육성.
- `post`: 실행마다 틀별 기본 레이어 상위 `top`개 구성에 실험 7 M3:k2 200평가를 붙이고 5덱을 다시 조립한다
  → `<dir2>/<실행>.post.json`. 조합 id = (시나리오, 배치 순서)라 같은 스쿼드는 실행이 달라도 한 번만 탐색한다(`<dir2>/jobs/`).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import importlib.util
import json
import os
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
EXP2 = HERE.parent / "02_score_distribution"
EXP4 = HERE.parent / "04_improvement_margin"
EXP6 = HERE.parent / "06_control_menu"
EXP7 = HERE.parent / "07_control_search"
sys.path[:0] = [str(EXP7), str(EXP6), str(HERE.parent.parent)]


def _load(name: str, path: Path, alias: str | None = None):
    """같은 이름의 모듈(실험 6 `search` 등)과 섞이지 않게 파일 경로로 읽는다. `alias`는 읽는 동안만 그 이름으로 둔다."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    old = sys.modules.get(alias) if alias else None
    try:
        spec.loader.exec_module(mod)
    finally:
        if alias:
            if old is None:
                sys.modules.pop(alias, None)
            else:
                sys.modules[alias] = old
    return mod


R2 = _load("exp2_run", EXP2 / "run.py")
_prev_run = sys.modules.get("run")
sys.modules["run"] = R2
try:
    S4 = _load("exp4_search", EXP4 / "search.py")
finally:
    if _prev_run is None:
        sys.modules.pop("run", None)
    else:
        sys.modules["run"] = _prev_run

import methods as M  # noqa: E402  (실험 7)
import select_comps as sc  # noqa: E402  (실험 6)

E8 = 1e8
POOL: dict[str, dict[str, Any]] = json.loads((EXP2 / "pool.json").read_text(encoding="utf-8"))["pool"]
BURST = {n: v["burst"] for n, v in POOL.items()}
RANKERS = json.loads((EXP2 / "ranker_squads.json").read_text(encoding="utf-8"))
RK_SQ = [tuple(s["squad"]) for s in RANKERS["squads"]]
FRAMES = frozenset(R2.TEMPLATES)  # (B1, B2, B3, A) 인원 — 실험 2 틀 5종

SEED_DEV = 20261007   # 실험 5와 같다
SEED_VAL = 20261030
CORE_USE = 0.95
TIERS = {  # 실험 5 deficit.py와 같다
    "상": {},
    "중": {"skill_levels": "7/7/7", "overload": {"우월 코드 대미지": 2, "공격력": 1}},
    "하": {"skill_levels": "4/4/4", "overload": {"우월 코드 대미지": 0, "공격력": 0}, "collection_stage": "없음"},
}

METHODS = ("L0", "L0k", "L1", "L2")
BUDGETS = (300, 800, 2000)
ROUND = 100
PACK_SHARE = 0.7
PARENTS, PER_PARENT = 40, 8
ORDER_TOP = 20
K_RANKERS = 30
STARTS = 4
MAX_SHARE = 2         # 대안 5덱 · 다중 출발: 앞의 5덱과 그대로 공유하는 덱(구성) 수 상한
L2_DECK_CAP = 0.4     # 한 라운드에서 한 덱을 바꾸는 수의 몫 상한
L2_KAPPA = 1.0       # 후보 값 = 예측 + κ · 잔차 표준편차
L2_BEAM = 3           # 덱 새로 짓기: 틀마다 첫 니케 후보 수
POST_METHOD, POST_BUDGET = "M3:k2", 200


# ---------------------------------------------------------------- 시나리오

def core_nikkes() -> list[str]:
    return sorted(n for n, v in POOL.items() if v["s40_use"] >= CORE_USE)


def _random_tiers(names: Iterable[str], rng: random.Random) -> dict[str, str]:
    return {n: rng.choices(["상", "중", "하"], [0.5, 0.3, 0.2])[0] for n in sorted(names)}


def dev_scenarios() -> list[dict[str, Any]]:
    """실험 5 `scenarios()`와 같은 순서 · 같은 시드."""
    core, out, picks = core_nikkes(), [], {}
    for k, tag in ((3, "A"), (3, "B"), (6, "A"), (6, "B")):
        picks[(k, tag)] = sorted(random.Random(f"{SEED_DEV}-{k}-{tag}").sample(core, k))
        out.append({"name": f"미보유 무작위 {k}명 {tag}", "missing": picks[(k, tag)], "tiers": {}})
    out.append({"name": "미보유 레드 후드", "missing": ["라피 : 레드 후드"], "tiers": {}})
    out.append({"name": "미보유 1덱 축", "missing": ["아니스 : 스타", "브리드 : 사일런트 트랙"], "tiers": {}})
    out.append({"name": "육성 무작위", "missing": [], "tiers": _random_tiers(POOL, random.Random(f"{SEED_DEV}-tiers"))})
    out.append({"name": "육성 핵심 6명 하", "missing": [], "tiers": {n: "하" for n in picks[(6, "A")]}})
    for i, s in enumerate(out, 1):
        s.update(id=f"d{i}", set="dev")
    return out


def val_scenarios() -> list[dict[str, Any]]:
    core, out, picks = core_nikkes(), [], {}
    for k, tag in ((3, "C"), (3, "D"), (6, "C"), (6, "D")):
        picks[(k, tag)] = sorted(random.Random(f"{SEED_VAL}-{k}-{tag}").sample(core, k))
        out.append({"name": f"미보유 무작위 {k}명 {tag}", "missing": picks[(k, tag)], "tiers": {}})
    for tag in ("C", "D"):
        out.append({"name": f"육성 무작위 {tag}", "missing": [],
                    "tiers": _random_tiers(POOL, random.Random(f"{SEED_VAL}-tiers-{tag}"))})
    out.append({"name": "육성 핵심 6명 하 C", "missing": [], "tiers": {n: "하" for n in picks[(6, "C")]}})
    miss = sorted(random.Random(f"{SEED_VAL}-3-E").sample(core, 3))
    out.append({"name": "혼합 E", "missing": miss,
                "tiers": _random_tiers((n for n in POOL if n not in miss), random.Random(f"{SEED_VAL}-tiers-E"))})
    for i, s in enumerate(out, 1):
        s.update(id=f"v{i}", set="val")
    return out


def scenarios(which: str) -> list[dict[str, Any]]:
    return dev_scenarios() if which == "dev" else val_scenarios()


class Account:
    """시나리오 하나의 로스터 · 요청 options."""

    def __init__(self, sc_: Mapping[str, Any]):
        self.id, self.name = sc_["id"], sc_["name"]
        self.missing = list(sc_["missing"])
        self.owned = {n: v for n, v in POOL.items() if n not in self.missing}
        self.names = sorted(self.owned)
        self.tier = {n: sc_["tiers"].get(n, "상") for n in self.owned}
        chars = {n: TIERS[t] for n, t in sorted(self.tier.items()) if t != "상"}
        self.options: dict[str, Any] = {"profile": {"base": "default", "chars": chars}} if chars else {}


# ---------------------------------------------------------------- 틀 · 조립

def frame(squad: Iterable[str]) -> tuple[int, int, int, int]:
    return sc.stage_counts(list(squad), BURST)


def skeleton(squad: Sequence[str]) -> str:
    return sc.skeleton(list(squad), BURST)


PACK_SLACK = 1e-6   # 라그랑주 상한의 부동소수 오차 여유(값 단위 억 — 해끼리의 실제 차이보다 훨씬 작다)
PACK_LAM_ITERS = 120


def _pack_lagrange(vs: Sequence[float], inc: np.ndarray, m: int, k: int, smax: int, lb: float) -> np.ndarray:
    """니케별 λ ≥ 0. 서로 겹치지 않는 구성 r개의 값 합 ≤ top_r(v − λ(구성)) + (안 쓴 니케 λ 상위 smax·r개 합)이
    어떤 λ에서도 맞으므로, 뿌리 문제(r = k)의 이 상한을 줄이는 λ를 하강(Polyak 걸음)으로 찾는다."""
    v = np.asarray(vs, dtype=float)
    lam = np.zeros(m + 1)
    best, best_lam = float("inf"), lam.copy()
    need = min(smax * k, m)
    mu, stall = 1.0, 0
    for _ in range(PACK_LAM_ITERS):
        red = v - lam[inc].sum(1)
        sel = np.argpartition(-red, k - 1)[:k] if len(v) > k else np.arange(len(v))
        top = np.argpartition(-lam[:m], need - 1)[:need] if m > need else np.arange(m)
        dual = float(red[sel].sum() + lam[top].sum())
        if dual < best - 1e-12:
            best, best_lam, stall = dual, lam.copy(), 0
        else:
            stall += 1
            if stall >= 8:
                mu, stall = mu / 2, 0
        g = np.zeros(m + 1)
        np.add.at(g, inc[sel].ravel(), -1.0)
        g[top] += 1.0
        g[m] = 0.0
        norm = float((g * g).sum())
        gap = dual - lb
        if norm == 0 or gap <= 1e-9 or mu < 1e-4:
            break
        lam = np.maximum(0.0, lam - mu * gap / norm * g)
        lam[m] = 0.0
    return best_lam[:m]


def pack_vals(vals: Mapping[frozenset, tuple[float, tuple]], k: int = 5,
              avoid: Sequence[set[frozenset]] = (), max_share: int = MAX_SHARE,
              limit: int | None = None) -> tuple[float, list[tuple[float, tuple]]]:
    """겹치지 않는 k개 구성의 값 합 최대(분기 한정, 실험 4 `pack`과 같은 탐색). `avoid`의 각 묶음과 그대로 공유하는
    구성이 `max_share`개 이하여야 한다. `limit`이 있으면 값 상위 그만큼만 본다.

    값 순 DFS에서 처음 만나는 최대 해를 돌려준다(값이 같으면 앞선 해). 2026-11-01 속도 개선 — 같은 DFS 순서와
    덧셈 순서를 지키고 가지치기만 더 한다: 남은 후보를 쓴 니케와 겹치지 않는 것으로 줄여 내려보내고, 상한은
    「다음 r개 값 합」과 라그랑주 상한 중 작은 쪽, 시작 하한은 앞쪽 후보 30개에서 시작한 탐욕 완성의 최고(보다 조금 아래).
    어느 가지치기도 지금 최선보다 엄격히 큰 해가 있는 가지를 자르지 않으므로 결과는 이전 판과 같다
    (`tests/test_exp09.py`가 이전 판과 비교한다). 한 덱만 크게 높은 계정(실험 19 t5)에서 이전 판이 몇 분씩 걸렸다.
    """
    cands = sorted(((v, sq, c) for c, (v, sq) in vals.items()), key=lambda t: (-t[0], t[1]))
    if limit is not None:
        cands = cands[:limit]
    n = len(cands)
    if k <= 0 or n < k:
        return (0.0, [])
    bit: dict[Any, int] = {}
    masks, rows = [], []
    for _, _, c in cands:
        b = sorted(bit.setdefault(x, len(bit)) for x in c)
        rows.append(b)
        mm = 0
        for x in b:
            mm |= 1 << x
        masks.append(mm)
    m = len(bit)
    smax = max(len(r) for r in rows)
    vs = [t[0] for t in cands]
    hits = [tuple(c in a for a in avoid) for _, _, c in cands] if avoid else None

    def share_ok(shares: tuple, i: int) -> tuple[tuple, bool]:
        ns = tuple(s + h for s, h in zip(shares, hits[i]))
        return ns, all(s <= max_share for s in ns)

    # 시작 하한: 앞쪽 후보마다 탐욕 완성 — DFS와 같은 순서 · 같은 덧셈이라 그 해의 DFS 값과 같다
    seed = float("-inf")
    for first in range(min(n, 30)):
        used, total, cnt, shares = 0, 0.0, 0, tuple(0 for _ in avoid)
        for j in range(first, n):
            if masks[j] & used:
                continue
            if hits is not None:
                ns, ok = share_ok(shares, j)
                if not ok:
                    continue
                shares = ns
            used |= masks[j]
            total += vs[j]
            cnt += 1
            if cnt == k:
                break
        if cnt == k and total > seed:
            seed = total
    have = seed > float("-inf")

    inc = np.full((n, smax), m, dtype=np.int64)
    for j, r in enumerate(rows):
        inc[j, :len(r)] = r
    lam = _pack_lagrange(vs, inc, m, k, smax, seed if have else 0.0).tolist()
    red = [vs[j] - sum(lam[x] for x in rows[j]) for j in range(n)]
    lam_order = sorted(range(m), key=lambda x: -lam[x])
    best: list[Any] = [seed - 1e-7 if have else float("-inf"), None, have]   # 값, 해(후보 번호), 가지치기 시작

    def dfs(L: list[int], used: int, path: list[int], total: float, shares: tuple, r: int) -> None:
        nL = len(L)
        if nL < r:
            return
        if r == 1:
            for i in L:
                if best[2] and total + vs[i] <= best[0]:
                    return
                if hits is not None and not share_ok(shares, i)[1]:
                    continue
                t = total + vs[i]
                if t > best[0]:
                    best[0], best[1], best[2] = t, path + [i], True
                return
            return
        need, lam_top, got = smax * r, 0.0, 0
        for x in lam_order:
            if got == need:
                break
            if not (used >> x) & 1:
                lam_top += lam[x]
                got += 1
        suf = [float("-inf")] * (nL + 1)   # suf[p] = L[p:]의 감한 값 상위 r개 합
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
            i = L[p]
            if best[2]:
                b = total
                for q in range(p, p + r):
                    b += vs[L[q]]
                if b <= best[0] or total + suf[p] + lam_top + PACK_SLACK <= best[0]:
                    return
            ns = shares
            if hits is not None:
                ns, ok = share_ok(shares, i)
                if not ok:
                    continue
            mi = masks[i]
            child = [j for j in L[p + 1:] if not masks[j] & mi]
            path.append(i)
            dfs(child, used | mi, path, total + vs[i], ns, r - 1)
            path.pop()

    dfs(list(range(n)), 0, [], 0.0, tuple(0 for _ in avoid), k)
    if best[1] is None:
        return (0.0, [])
    return (best[0], [(vs[i], cands[i][1]) for i in best[1]])


def stage_pattern() -> dict[tuple, tuple[str, ...]]:
    """틀 → 랭커 덱에서 가장 흔한 자리별 단계 배열(덱 새로 짓기의 배치 순서)."""
    cnt: dict[tuple, Counter] = {}
    for s in RANKERS["squads"]:
        sq = tuple(s["squad"])
        cnt.setdefault(frame(sq), Counter())[tuple(BURST[n] for n in sq)] += s["count"]
    out = {f: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] for f, c in cnt.items()}
    for f in FRAMES - set(out):  # 랭커 덱에 없는 틀(레드 후드 틀): 단계 1 · 2 · A · 3 순
        out[f] = tuple(s for s, c in zip("12A3", (f[0], f[1], f[3], f[2])) for _ in range(c))
    return out


PATTERN = stage_pattern()


# ---------------------------------------------------------------- 랭커 옮기기

def transplant(decks: Sequence[tuple], owned: Mapping[str, Mapping[str, Any]]) -> list[tuple]:
    """실험 5 `transplant`와 같다."""
    used = {n for d in decks for n in d if n in owned}
    out = []
    for d in decks:
        nd = []
        for n in d:
            if n not in owned:
                cands = [m for m in owned if m not in used and owned[m]["burst"] == BURST[n]]
                cands = cands or [m for m in owned if m not in used]
                n = max(cands, key=lambda m: (owned[m]["s40_use"], owned[m]["prior"], m))
                used.add(n)
            nd.append(n)
        out.append(tuple(nd))
    return out


def ranker_order(owned: Mapping[str, Any]) -> list[int]:
    """옮길 랭커 순서: (없는 니케 수, −구성 사용 수 합, 순번)."""
    def key(i):
        p = RANKERS["players"][i]
        miss = sum(n not in owned for j in p["squads"] for n in RK_SQ[j])
        pop = sum(RANKERS["squads"][j]["count"] for j in p["squads"])
        return (miss, -pop, i)
    return sorted(range(len(RANKERS["players"])), key=key)


# ---------------------------------------------------------------- 평가 상태

class Session:
    """한 실행의 평가 기록. 같은 스쿼드(순서 포함)는 한 번만 요청하고, 예산을 넘는 요청은 앞에서부터 자른다."""

    def __init__(self, acct: Account, ev: Any, budget: int):
        self.acct, self.ev, self.budget = acct, ev, budget
        self.book = S4.Book()
        self.asked: set[tuple] = set()
        self.records: list[dict[str, Any]] = []
        self.used = 0

    @property
    def left(self) -> int:
        return self.budget - self.used

    def fresh(self, sq: tuple) -> bool:
        return sq not in self.asked

    def run(self, squads: Iterable[tuple], phase: str, cap: int | None = None) -> int:
        from nikke_opt.evaluator import EvalRequest
        room = self.left if cap is None else min(self.left, cap)
        todo = [sq for sq in dict.fromkeys(squads) if sq not in self.asked][:max(room, 0)]
        if not todo:
            return 0
        res = self.ev.evaluate([EvalRequest(sq, boss=None, options=self.acct.options) for sq in todo])
        for sq, r in zip(todo, res):
            self.asked.add(sq)
            dmg = None if r.error else r.total_damage
            if dmg is not None:
                self.book.add(sq, dmg / E8)
            self.records.append({"squad": list(sq), "total_damage": dmg, "phase": phase,
                                 "error": r.error, "cached": r.cached})
        self.used += len(todo)
        return len(todo)

    def pack(self) -> tuple[float, list[tuple[float, tuple]]]:
        return pack_vals(self.book.best)


# ---------------------------------------------------------------- 후보 생성

def raw_moves(decks: Sequence[tuple], owned: Mapping[str, Any]) -> list[tuple[tuple[int, ...], list[tuple]]]:
    """최선 5덱을 고치는 수 (바꾸는 덱 번호, 새 스쿼드들): 한 명 교체(다른 덱이 안 쓰는 니케, 틀이 바뀌어도 실험 2 틀 5종 안) ·
    두 덱 맞교환(같은 단계, 또는 두 덱 모두 틀 5종 안)."""
    used = {n for d in decks for n in d}
    out = []
    for i, d in enumerate(decks):
        for j, n in enumerate(d):
            for m in owned:
                if m in used:
                    continue
                nd = d[:j] + (m,) + d[j + 1:]
                if BURST[m] == BURST[n] or frame(nd) in FRAMES:
                    out.append(((i,), [nd]))
    for (ia, a), (ib, b) in combinations(enumerate(decks), 2):
        for j, n in enumerate(a):
            for k, m in enumerate(b):
                na, nb = a[:j] + (m,) + a[j + 1:], b[:k] + (n,) + b[k + 1:]
                if BURST[n] == BURST[m] or (frame(na) in FRAMES and frame(nb) in FRAMES):
                    out.append(((ia, ib), [na, nb]))
    return out


def build_decks(avail: Iterable[str], score: Callable) -> list[tuple]:
    """남은 니케로 틀마다 대리 모델 최고 스쿼드를 탐욕으로 짓는다(첫 니케 후보 L2_BEAM개). 배치 순서는 그 틀의 흔한 단계 배열."""
    avail = sorted(avail)
    out = []
    for f in sorted(FRAMES):
        need = dict(zip("123A", f))
        if any(sum(BURST[m] == s for m in avail) < c for s, c in need.items()):
            continue
        firsts = sorted((m for m in avail if need[BURST[m]] > 0),
                        key=lambda m: (-score(frozenset([m])), m))[:L2_BEAM]
        for m0 in firsts:
            cur, left = [m0], dict(need)
            left[BURST[m0]] -= 1
            while len(cur) < 5:
                opts = [m for m in avail if m not in cur and left[BURST[m]] > 0]
                m = max(opts, key=lambda x: (score(frozenset(cur + [x])), x))
                cur.append(m)
                left[BURST[m]] -= 1
            by = {s: [m for m in cur if BURST[m] == s] for s in "123A"}
            out.append(tuple(by[s].pop(0) for s in PATTERN[f]))
    return out


# ---------------------------------------------------------------- 기법

def _take_factory(sess: Session, pick: list[tuple], seen: set[frozenset], n: int):
    def take(sqs: Sequence[tuple]) -> int:
        """실험 5 `take`: 모두 새로 넣을 수 있으면 넣는다. 넣은 수."""
        new = [s for s in sqs if sess.fresh(s) and frozenset(s) not in sess.book.best and frozenset(s) not in seen]
        if not new or len(pick) + len(new) > n:
            return 0
        pick.extend(new)
        seen.update(frozenset(s) for s in new)
        return len(new)
    return take


def local_round(sess: Session, n: int, starts: list[set[frozenset]] | None) -> list[tuple]:
    """실험 5 라운드: 5덱 고치기 70%(출발이 여럿이면 몫을 나눔) + 이웃 30%. 출발마다 고른 구성을 그 계보에 더한다."""
    acct = sess.acct
    score = S4.fit(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = _take_factory(sess, pick, seen, n)
    share = int(n * PACK_SHARE)
    if starts is None:
        groups = [([sq for _, sq in sess.pack()[1]], None)]
    else:
        groups = [([sq for _, sq in pack_vals({c: v for c, v in sess.book.best.items() if c in lin})[1]], lin)
                  for lin in starts]
    quotas = [share // len(groups) + (i < share % len(groups)) for i in range(len(groups))]
    for (decks, lin), q in zip(groups, quotas):
        got = 0
        lo = len(pick)
        for _, new in S4.pack_moves(decks, acct.owned, score):
            if got >= q:
                break
            got += take(new)
        if lin is not None:
            lin.update(frozenset(s) for s in pick[lo:])
    parents = sorted(sess.book.best.values(), reverse=True)[:PARENTS]
    cands = []
    for _, sq in parents:
        lst = [(score(frozenset(nb)), nb) for nb in S4.neighbors(sq, acct.owned) if frozenset(nb) not in sess.book.best]
        cands += sorted(lst, reverse=True)[:PER_PARENT]
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick


def surrogate_round(sess: Session, n: int) -> list[tuple]:
    """L2: 최선 5덱을 고치는 넓은 수(틀이 바뀌는 교체 · 맞교환 · 덱 새로 짓기)를 예상 5덱 이득으로 줄 세워 위에서부터 고른다.
    이득 = Σ 새 스쿼드 값 − Σ 바꾸는 덱의 실제 값. 새 스쿼드 값은 평가했으면 실제, 아니면 예측 + κ·잔차 sd(낙관 보정 —
    릿지 예측은 상위에서 낮게 나온다). 한 덱을 바꾸는 수는 라운드의 L2_DECK_CAP 몫까지."""
    acct, book = sess.acct, sess.book
    score = S4.fit(book, acct.names)
    ys = np.array([v for v, _ in book.best.values()])
    ps = np.array([score(c) for c in book.best])
    sd = float(np.sqrt(np.mean((ys - ps) ** 2))) if len(ys) > 1 else 0.0
    pk = sess.pack()
    decks = [sq for _, sq in pk[1]]
    cur = [v for v, _ in pk[1]]
    memo: dict[frozenset, float] = {}

    def val(sq):
        c = frozenset(sq)
        if c in book.best:
            return book.best[c][0]
        if c not in memo:
            memo[c] = score(c) + L2_KAPPA * sd
        return memo[c]

    moves = raw_moves(decks, acct.owned)
    for i in range(len(decks)):
        others = {m for j, d in enumerate(decks) if j != i for m in d}
        moves += [((i,), [nd]) for nd in build_decks((m for m in acct.owned if m not in others), score)]
    ranked = sorted(((sum(val(x) for x in new) - sum(cur[i] for i in idx), idx, new) for idx, new in moves),
                    key=lambda t: (-t[0], t[1], t[2]))
    cap = max(1, int(n * L2_DECK_CAP))
    per = Counter()
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    for _, idx, new in ranked:
        if len(pick) >= n:
            break
        if any(per[i] >= cap for i in idx):
            continue
        fresh = [x for x in new if sess.fresh(x) and frozenset(x) not in book.best and frozenset(x) not in seen]
        if not fresh or len(pick) + len(fresh) > n:
            continue
        pick += fresh
        seen.update(frozenset(x) for x in fresh)
        for i in idx:
            per[i] += 1
    return pick


def run_method(acct: Account, method: str, budget: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sess = Session(acct, ev, budget)
    t0, sims0 = time.time(), ev.sim_count
    reserve = budget // 8
    order = ranker_order(acct.owned)
    k = len(order) if method == "L0" else K_RANKERS
    players = [(i, transplant([RK_SQ[j] for j in RANKERS["players"][i]["squads"]], acct.owned)) for i in order[:k]]
    sess.run([d for _, decks in players for d in decks], "옮기기", cap=budget - reserve)
    trans_evals = sess.used
    p0 = sess.pack()
    history = [{"evals": sess.used, "pack": p0[0]}]
    done = [(i, decks) for i, decks in players if all(d in sess.book.seen for d in decks)]
    sums = sorted(sum(sess.book.seen[d] for d in decks) for _, decks in done)
    baseline = None
    if done:
        bi, bd = max(done, key=lambda t: sum(sess.book.seen[d] for d in t[1]))
        baseline = {"players_done": len(done), "best": sum(sess.book.seen[d] for d in bd),
                    "best_player": RANKERS["players"][bi]["player"], "median": float(np.median(sums)),
                    "repack": p0[0]}
    starts = None
    if method == "L1":
        starts, avoid = [], []
        for _ in range(STARTS):
            v, ch = pack_vals(sess.book.best, avoid=avoid)
            if not ch:
                break
            s = {frozenset(sq) for _, sq in ch}
            starts.append(set(s))
            avoid.append(s)
    while sess.left > reserve:
        n = min(ROUND, sess.left - reserve)
        if method == "L2":
            pick = surrogate_round(sess, n)
        else:
            pick = local_round(sess, n, starts)
        if not pick or not sess.run(pick, f"탐색 {len(history)}", cap=n):
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0]})
    best = sess.pack()
    tops = [sq for _, sq in best[1]] + [sq for _, sq in sorted(sess.book.best.values(), reverse=True)[:ORDER_TOP]]
    orders = list(dict.fromkeys(p for sq in dict.fromkeys(tops) for p in R2.distinct_orders(sq, BURST)
                                if sess.fresh(p)))
    sess.run(orders, "순서")
    final = sess.pack()
    history.append({"evals": sess.used, "pack": final[0]})
    alt = pack_vals(sess.book.best, avoid=[{frozenset(sq) for _, sq in final[1]}])
    summ = {"scenario": acct.id, "name": acct.name, "method": method, "budget": budget, "evals": sess.used,
            "transplant_players": len(players), "transplant_evals": trans_evals, "errors": sum(
                r["error"] is not None for r in sess.records),
            "baseline": baseline, "history": history,
            "final": {"total": final[0], "squads": [[v, list(sq)] for v, sq in final[1]]},
            "alt": {"total": alt[0], "squads": [[v, list(sq)] for v, sq in alt[1]]},
            "sims_during": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1)}
    return summ, sess.records


# ---------------------------------------------------------------- 실행 명령

def run_name(sid: str, method: str, budget: int) -> str:
    return f"{sid}_{method}_{budget}"


def cmd_search(args: argparse.Namespace) -> int:
    scs = scenarios(args.set)
    if args.only:
        want = set(args.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    methods = args.methods.split(",")
    budgets = [int(b) for b in args.budgets.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    tasks = [(s, m, b) for b in sorted(budgets, reverse=True) for s in scs for m in methods
             if not (args.out / f"{run_name(s['id'], m, b)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, m, b = task
        acct = Account(s)
        summ, recs = run_method(acct, m, b, ev)
        name = run_name(s["id"], m, b)
        with gzip.open(args.out / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        (args.out / f"{name}.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with lock:
            print(json.dumps({"run": name, "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "s": summ["seconds"], "t": round(time.time() - t0), "sims": ev.sim_count},
                             ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in [pool.submit(work, t) for t in tasks]:
                f.result()
        print(f"실행 {len(tasks)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · {time.time() - t0:.0f}초 · "
              f"평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


def load_records(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def book_of(records: Iterable[Mapping[str, Any]]) -> dict[frozenset, tuple[float, tuple]]:
    b = S4.Book()
    for r in records:
        if r["total_damage"] is not None:
            b.add(tuple(r["squad"]), r["total_damage"] / E8)
    return b.best


def post_targets(best: Mapping[frozenset, tuple[float, tuple]], top: int) -> list[tuple]:
    """틀별 기본 레이어 상위 `top`개 구성의 최선 순서(동률은 순서 tuple 순)."""
    by: dict[str, list[tuple[float, tuple]]] = {}
    for v, sq in best.values():
        by.setdefault(skeleton(sq), []).append((v, sq))
    out = []
    for sk in sorted(by):
        out += [sq for _, sq in sorted(by[sk], key=lambda t: (-t[0], t[1]))[:top]]
    return out


def post_id(sid: str, sq: Sequence[str]) -> str:
    return f"{sid}|" + ">".join(sq)


def post_file(jobs: Path, cid: str) -> Path:
    return jobs / (hashlib.sha256(cid.encode()).hexdigest()[:16] + ".json")


def repack_post(best: Mapping[frozenset, tuple[float, tuple]], post: Mapping[tuple, float]
                ) -> tuple[float, list[tuple[float, tuple]]]:
    vals = {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in best.items()}
    return pack_vals(vals)


def cmd_post(args: argparse.Namespace) -> int:
    runs = sorted(p for p in args.runs.glob("*.json"))
    if args.only:
        want = set(args.only.split(","))
        runs = [p for p in runs if p.stem.split("_")[0] in want or p.stem in want]
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = args.out / "jobs"
    jobs.mkdir(exist_ok=True)
    accts = {s["id"]: Account(s) for s in dev_scenarios() + val_scenarios()}
    plans = []
    for p in runs:
        summ = json.loads(p.read_text(encoding="utf-8"))
        best = book_of(load_records(p.with_suffix(".jsonl.gz")))
        targets = post_targets(best, args.top)
        plans.append((p.stem, summ, best, targets))
    need = {}
    for _, summ, _, targets in plans:
        for sq in targets:
            cid = post_id(summ["scenario"], sq)
            if not post_file(jobs, cid).exists():
                need[cid] = (summ["scenario"], sq)
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()

    def work(item):
        cid, (sid, sq) = item
        acct = accts[sid]
        space = M.Space(list(sq), base=acct.options)
        r = M.run_job({"id": cid, "squad": list(sq)}, POST_METHOD, ev, budget=POST_BUDGET, out=None, space=space)
        r["squad"] = list(sq)
        post_file(jobs, cid).write_text(json.dumps(r, ensure_ascii=False) + "\n", encoding="utf-8")

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, f in enumerate([pool.submit(work, it) for it in sorted(need.items())]):
                f.result()
                if (i + 1) % 20 == 0:
                    print(f"후처리 {i + 1}/{len(need)} · 시뮬 {ev.sim_count} · {time.time() - t0:.0f}초",
                          file=sys.stderr, flush=True)
        sims = ev.sim_count
    for stem, summ, best, targets in plans:
        res = {}
        for sq in targets:
            r = json.loads(post_file(jobs, post_id(summ["scenario"], sq)).read_text(encoding="utf-8"))
            res[sq] = r
        post = {sq: r["best_damage"] / E8 for sq, r in res.items() if r["best_damage"] is not None}
        total, ch = repack_post(best, post)
        out = {"run": stem, "scenario": summ["scenario"], "method": summ["method"], "budget": summ["budget"],
               "top": args.top, "targets": len(targets), "post_evals": sum(r["evals"] for r in res.values()),
               "pre": summ["final"]["total"], "total": total,
               "squads": [[v, list(sq), sq in post] for v, sq in ch],
               "gains": {">".join(sq): post[sq] / best[frozenset(sq)][0] - 1 for sq in post}}
        (args.out / f"{stem}.top{args.top}.post.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                                  encoding="utf-8")
    print(f"후처리 조합 {len(need)}개 · 시뮬 {sims}회 · {time.time() - t0:.0f}초", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--methods", default=",".join(METHODS))
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=4)
    p = sub.add_parser("post")
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--only")
    p.add_argument("--workers", type=int, default=8)
    sub.add_parser("scenarios")
    args = ap.parse_args(argv)
    if args.cmd == "scenarios":
        for s_ in dev_scenarios() + val_scenarios():
            t = Counter(v for v in s_["tiers"].values() if v != "상")
            print(s_["id"], s_["name"], "미보유", s_["missing"], "중", t["중"], "하", t["하"])
        return 0
    return cmd_search(args) if args.cmd == "search" else cmd_post(args)


if __name__ == "__main__":
    sys.exit(main())
