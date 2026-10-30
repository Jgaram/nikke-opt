"""실험 10 — 랭커 정보 없는 출발과 국소 최적 탈출 실행기 (README §비교 기법 · §탈출 E).

    source .cache/evaluators.env && python experiments/10_rankerless_start/run10.py precompute --pool 60 --out <dir>
    source .cache/evaluators.env && python experiments/10_rankerless_start/run10.py search --set val --pool 60 --out <dir>
        [--methods K+E,R,R+E,G,G+E,P,P+E] [--budgets 300,800,2000] [--only v1,v2] [--pre <dir>] [--workers 4]
    python experiments/10_rankerless_start/run10.py import-k --set val --exp9 experiments/09_account_pack/run_log --out <dir>

- `precompute`: 사전 계산 계정(풀 전원 보유 · 전원 상)에서 G+E 5,000평가 → `<dir>/precompute_P<pool>.json`
  (덱 2개 이하만 공유하는 최선 5덱 8벌 · 마지막 릿지의 니케 계수). P · P+E가 읽는다.
- `search`: (시나리오, 기법, 예산)마다 `<dir>/<sid>_P<pool>_<기법>_<예산>.json`(요약, SESSIONS.md 형식)과 `.jsonl.gz`(평가 기록).
  이미 있는 실행은 건너뛴다. 평가는 기본 레이어(운용 없음) + 시나리오 육성, 후처리 없음.
- `import-k`: 실험 9 L0k 기록을 K(P60) 요약 형식으로 옮긴다.

랭커 없는 기법(R · G · P와 +E)은 랭커 덱 · 사용률 · prior · PATTERN을 읽지 않는다 — 계정 로스터에는 버스트 단계만 둔다(테스트로 막는다).
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
EXP9 = HERE.parent / "09_account_pack"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R9 = sys.modules.get("run9") or _load("run9", EXP9 / "run9.py")
S4, R2 = R9.S4, R9.R2

E8 = 1e8
ROSTER = json.loads((HERE / "roster_ssr.json").read_text(encoding="utf-8"))
BURST_ALL: dict[str, str] = dict(ROSTER["roster"])  # SSR 177명 → 버스트 단계(공개 원본 데이터)
P60 = tuple(sorted(R9.POOL))
P177 = tuple(sorted(BURST_ALL))
POOLS = {60: P60, 177: P177}
assert all(BURST_ALL[n] == R9.BURST[n] for n in P60)

# 구조 틀 규칙: 1 · 2 · 3단계 각 1명 이상, 3단계 + A ≥ 2, A는 레드 후드 하나뿐 → 6틀 (B1, B2, B3, A)
STRUCT_FRAMES = tuple(f for f in product(range(1, 4), range(1, 4), range(1, 4), range(2))
                      if sum(f) == 5 and f[2] + f[3] >= 2)

METHODS = ("K", "K+E", "R", "R+E", "G", "G+E", "P", "P+E")
NEW_METHODS = METHODS[1:]
RANKERLESS = ("R", "R+E", "G", "G+E", "P", "P+E")
BUDGETS = (300, 800, 2000)
ROUND = R9.ROUND
DESIGN_MULT = 3        # 설계 크기 = 보유 니케 수 × 3 / 5
G_ROUND = 100          # 구성 라운드 평가 수
G_KAPPA = 1.0          # 낙관 보정 κ
G_BEAM = 3             # 틀마다 첫 니케 후보 수 · 첫 덱 후보 수
KICK_DECKS = 2
PRE_BUDGET, PRE_SETS = 5000, 8
EXT_TIER_TAG = {"v5": "C", "v6": "D", "v8": "E"}  # 육성 무작위 시나리오 → 더한 니케 등급 시드


# ---------------------------------------------------------------- 계정

class Account10:
    """시나리오 하나의 로스터(풀 60 · 177) · 요청 options. 랭커 없는 기법의 로스터에는 버스트 단계만 둔다."""

    def __init__(self, sc_: Mapping[str, Any], pool: int = 60, rankerless: bool = True):
        self.id, self.name, self.pool = sc_["id"], sc_["name"], pool
        self.missing = list(sc_["missing"])
        tiers = dict(sc_["tiers"])
        if pool == 177:
            tiers.update(ext_tiers(sc_))
        names = [n for n in POOLS[pool] if n not in self.missing]
        if rankerless:
            self.owned = {n: {"burst": BURST_ALL[n]} for n in names}
        else:  # K: 풀 밖 니케는 사용률 · prior −1로 대체 순서 뒤로 간다
            self.owned = {n: dict(R9.POOL[n]) if n in R9.POOL else {"burst": BURST_ALL[n], "s40_use": -1.0, "prior": -1.0}
                          for n in names}
        self.names = sorted(self.owned)
        self.tier = {n: tiers.get(n, "상") for n in self.owned}
        chars = {n: R9.TIERS[t] for n, t in sorted(self.tier.items()) if t != "상"}
        self.options: dict[str, Any] = {"profile": {"base": "default", "chars": chars}} if chars else {}


def ext_tiers(sc_: Mapping[str, Any]) -> dict[str, str]:
    """P177에서 더한 117명의 등급: 육성 무작위 시나리오는 같은 규칙(상 50 · 중 30 · 하 20%)으로 새 시드, 나머지는 모두 상."""
    tag = EXT_TIER_TAG.get(sc_["id"]) if sc_.get("set") == "val" else None
    if tag is None:
        return {}
    ext = [n for n in P177 if n not in R9.POOL]
    return R9._random_tiers(ext, random.Random(f"{R9.SEED_VAL}-tiers-{tag}-ext"))


def pre_scenario() -> dict[str, Any]:
    return {"id": "pre", "name": "사전 계산(전원 보유 · 상)", "missing": [], "tiers": {}, "set": "pre"}


def scenarios(which: str) -> list[dict[str, Any]]:
    return R9.scenarios(which)


# ---------------------------------------------------------------- 대리 모델

class DualFit:
    """실험 4 `fit`(니케 + 짝 릿지, 절편 벌점 없음)과 같은 해를 쌍대형으로 푼다 — 짝 특성이 많은 P177용.
    k(c, c_i) = |c∩c_i| / λ_u + C(|c∩c_i|, 2) / λ_p (평가한 구성의 짝은 모두 특성이므로)."""

    def __init__(self, book: Any, names: Sequence[str]):
        self.ni = {n: i for i, n in enumerate(names)}
        comps = list(book.best)
        self.M = np.zeros((len(comps), len(names)))
        for r, c in enumerate(comps):
            for n in c:
                self.M[r, self.ni[n]] = 1.0
        y = np.array([book.best[c][0] for c in comps])
        S = self.M @ self.M.T
        K = self._k(S) + np.eye(len(comps))
        uv = np.linalg.solve(K, np.c_[y, np.ones(len(comps))])
        self.b = float(uv[:, 0].sum() / uv[:, 1].sum())
        self.alpha = uv[:, 0] - self.b * uv[:, 1]

    @staticmethod
    def _k(S):
        return S / S4.LAM_U + S * (S - 1) / 2 / S4.LAM_P

    def __call__(self, c: Iterable[str]) -> float:
        idx = [self.ni[n] for n in c]
        if not idx:
            return self.b
        s = self.M[:, idx].sum(1)
        return float(self.b + self.alpha @ self._k(s))

    def add_scores(self, cur: Sequence[str], opts: Sequence[str]) -> list[float]:
        s = self.M[:, [self.ni[n] for n in cur]].sum(1) if cur else np.zeros(self.M.shape[0])
        S = s[:, None] + self.M[:, [self.ni[n] for n in opts]]
        return list(self.b + self.alpha @ self._k(S))


def fit_for(pool: int) -> Callable[[Any, Sequence[str]], Callable]:
    """P60은 실험 9와 같은 `S4.fit`(K 재현), P177은 같은 해의 쌍대형."""
    return S4.fit if pool == 60 else DualFit


def add_scores(score: Callable, cur: Sequence[str], opts: Sequence[str]) -> list[float]:
    if hasattr(score, "add_scores"):
        return score.add_scores(cur, opts)
    return [score(frozenset(list(cur) + [x])) for x in opts]


def resid_sd(book: Any, score: Callable) -> float:
    if len(book.best) < 2:
        return 0.0
    ys = np.array([v for v, _ in book.best.values()])
    ps = np.array([score(c) for c in book.best])
    return float(np.sqrt(np.mean((ys - ps) ** 2)))


# ---------------------------------------------------------------- 구조 틀 · 생성

def frame_of(squad: Iterable[str], burst: Mapping[str, str]) -> tuple[int, int, int, int]:
    c = Counter(burst[n] for n in squad)
    return (c["1"], c["2"], c["3"], c["A"])


def by_stage(avail: Iterable[str], burst: Mapping[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {s: [] for s in "123A"}
    for n in sorted(avail):
        out[burst[n]].append(n)
    return out


def feasible(stages: Mapping[str, Sequence[str]]) -> list[tuple]:
    return [f for f in STRUCT_FRAMES if all(len(stages[s]) >= c for s, c in zip("123A", f))]


def arrange(members: Mapping[str, list[str]]) -> tuple[str, ...]:
    """배치 순서: 단계 1 · 2 · A · 3."""
    return tuple(members.get("1", []) + members.get("2", []) + members.get("A", []) + members.get("3", []))


def struct_squad(avail: Iterable[str], counts: Counter, rng: random.Random,
                 burst: Mapping[str, str]) -> tuple[str, ...] | None:
    """균형 무작위 스쿼드 하나: 만들 수 있는 구조 틀을 균등하게 고르고, 자리마다 그 단계에서 지금까지 가장 적게 나온 니케
    (동점은 무작위). 같은 단계 안의 배치는 무작위."""
    stages = by_stage(avail, burst)
    frames = feasible(stages)
    if not frames:
        return None
    f = rng.choice(frames)
    members: dict[str, list[str]] = {}
    for s, c in zip("123A", f):
        chosen: list[str] = []
        for _ in range(c):
            opts = [m for m in stages[s] if m not in chosen]
            lo = min(counts[m] for m in opts)
            chosen.append(rng.choice([m for m in opts if counts[m] == lo]))
        rng.shuffle(chosen)
        members[s] = chosen
    return arrange(members)


def design(names: Sequence[str], burst: Mapping[str, str], rng: random.Random, n: int | None = None,
           avoid: Iterable[frozenset] = ()) -> list[tuple[str, ...]]:
    """균형 무작위 설계: 보유 니케 수 × 3 / 5개. 구성이 겹치면 다시 뽑는다(그때는 횟수를 세지 않는다)."""
    n = len(names) * DESIGN_MULT // 5 if n is None else n
    counts: Counter = Counter()
    seen = set(avoid)
    out: list[tuple[str, ...]] = []
    tries = 0
    while len(out) < n and tries < 50 * n + 100:
        tries += 1
        sq = struct_squad(names, counts, rng, burst)
        if sq is None:
            break
        if frozenset(sq) in seen:
            continue
        seen.add(frozenset(sq))
        counts.update(sq)
        out.append(sq)
    return out


def greedy_squads(avail: Iterable[str], score: Callable, burst: Mapping[str, str],
                  rng: random.Random, beam: int = G_BEAM) -> list[tuple[str, ...]]:
    """틀마다 첫 니케 후보 `beam`개로 대리 모델 탐욕 구성(실험 9 `build_decks`의 구조 틀 · 랭커 없는 판). 배치는 1 · 2 · A · 3,
    같은 단계 안은 무작위."""
    avail = sorted(avail)
    stages = by_stage(avail, burst)
    single = dict(zip(avail, add_scores(score, [], avail)))
    out = []
    for f in feasible(stages):
        need = dict(zip("123A", f))
        firsts = sorted((m for m in avail if need[burst[m]] > 0), key=lambda m: (-single[m], m))[:beam]
        for m0 in firsts:
            cur, left = [m0], dict(need)
            left[burst[m0]] -= 1
            while len(cur) < 5:
                opts = [m for m in avail if m not in cur and left[burst[m]] > 0]
                vals = add_scores(score, cur, opts)
                m = max(zip(vals, opts))[1]
                cur.append(m)
                left[burst[m]] -= 1
            members = {s: [m for m in cur if burst[m] == s] for s in "123A"}
            for v in members.values():
                rng.shuffle(v)
            out.append(arrange(members))
    return out


# ---------------------------------------------------------------- 조립 보조

def pack_alt20(vals: Mapping[frozenset, tuple[float, tuple]], best: Sequence[tuple], k: int = 5,
               max_share: int = R9.MAX_SHARE, max_nikke: int = 20) -> tuple[float, list[tuple[float, tuple]]]:
    """대안 (b): 최선 5덱과 덱을 `max_share`개 이하, 니케를 `max_nikke`명 이하만 공유하는 최선 5덱(분기 한정)."""
    bc = {frozenset(sq) for sq in best}
    bn = {n for sq in best for n in sq}
    cands = sorted(((v, sq, c, len(c & bn)) for c, (v, sq) in vals.items()), key=lambda t: (-t[0], t[1]))
    res: list[Any] = [float("-inf"), []]

    def dfs(start, used, chosen, total, dshare, nshare):
        if len(chosen) == k:
            if total > res[0]:
                res[:] = [total, list(chosen)]
            return
        for i in range(start, len(cands)):
            d, sq, c, ns = cands[i]
            if res[1] and total + d * (k - len(chosen)) <= res[0]:
                return
            if not used.isdisjoint(c):
                continue
            nd, nn = dshare + (c in bc), nshare + ns
            if nd > max_share or nn > max_nikke:
                continue
            chosen.append((d, sq))
            dfs(i + 1, used | c, chosen, total + d, nd, nn)
            chosen.pop()

    dfs(0, frozenset(), [], 0.0, 0, 0)
    return (res[0], res[1]) if res[1] else (0.0, [])


def shared_nikkes(a: Sequence[tuple], b: Sequence[tuple]) -> int:
    return len({n for sq in a for n in sq} & {n for sq in b for n in sq})


def pack_dict(p: tuple[float, list[tuple[float, tuple]]], best: Sequence[tuple] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"total": p[0], "squads": [[v, list(sq)] for v, sq in p[1]]}
    if best is not None:
        out["shared_nikkes"] = shared_nikkes([sq for _, sq in p[1]], best) if p[1] else 0
    return out


def lineage_pack(sess: Any, lineage: set[frozenset] | None) -> float:
    if lineage is None:
        return sess.pack()[0]
    return R9.pack_vals({c: v for c, v in sess.book.best.items() if c in lineage})[0]


def transplant_coef(decks: Sequence[tuple], owned: Mapping[str, Any], coef: Mapping[str, float],
                    burst: Mapping[str, str]) -> list[tuple]:
    """P: 사전 계산 5덱 옮기기 — 없는 니케는 같은 단계 · 니케 계수 순으로 대체(실험 5 `transplant`의 대체 순서만 바꿈)."""
    used = {n for d in decks for n in d if n in owned}
    out = []
    for d in decks:
        nd = []
        for n in d:
            if n not in owned:
                cands = [m for m in owned if m not in used and burst[m] == burst[n]]
                cands = cands or [m for m in owned if m not in used]
                n = max(cands, key=lambda m: (coef.get(m, float("-inf")), m))
                used.add(n)
            nd.append(n)
        out.append(tuple(nd))
    return out


# ---------------------------------------------------------------- 탐색 단계

def local_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable) -> list[tuple]:
    """실험 9 `local_round`(L0 · L1의 계보 하나)와 같다 — 대리 모델만 주입한다."""
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = R9._take_factory(sess, pick, seen, n)
    share = int(n * R9.PACK_SHARE)
    if lineage is None:
        decks = [sq for _, sq in sess.pack()[1]]
    else:
        decks = [sq for _, sq in R9.pack_vals({c: v for c, v in sess.book.best.items() if c in lineage})[1]]
    got = 0
    for _, new in S4.pack_moves(decks, acct.owned, score):
        if got >= share:
            break
        got += take(new)
    if lineage is not None:
        lineage.update(frozenset(s) for s in pick)
    parents = sorted(sess.book.best.values(), reverse=True)[:R9.PARENTS]
    cands = []
    for _, sq in parents:
        lst = [(score(frozenset(nb)), nb) for nb in S4.neighbors(sq, acct.owned) if frozenset(nb) not in sess.book.best]
        cands += sorted(lst, reverse=True)[:R9.PER_PARENT]
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick


def construct(sess: Any, reserve: int, fitf: Callable, burst: Mapping[str, str], rng: random.Random) -> int:
    """G 구성 라운드: 맞추고 → 첫 덱 후보 3개마다 나머지 4덱을 탐욕 구성 → 새 스쿼드를 평가 → 다시 맞춘다. G_ROUND평가까지."""
    acct, book = sess.acct, sess.book
    used = 0
    while used < G_ROUND and sess.left > reserve:
        score = fitf(book, acct.names)
        sd = resid_sd(book, score)
        memo: dict[frozenset, float] = {}

        def val(sq):
            c = frozenset(sq)
            if c in book.best:
                return book.best[c][0]
            if c not in memo:
                memo[c] = score(c) + G_KAPPA * sd
            return memo[c]

        firsts: list[tuple] = []
        for sq in sorted(greedy_squads(acct.names, score, burst, rng), key=lambda s: (-val(s), s)):
            if all(frozenset(sq) != frozenset(x) for x in firsts):
                firsts.append(sq)
            if len(firsts) >= G_BEAM:
                break
        new: list[tuple] = []
        for d0 in firsts:
            decks, avail = [d0], set(acct.names) - set(d0)
            for _ in range(4):
                cands = greedy_squads(avail, score, burst, rng)
                if not cands:
                    break
                d = max(cands, key=lambda s: (val(s), s))
                decks.append(d)
                avail -= set(d)
            new += decks
        seen: set[frozenset] = set()
        fresh = []
        for sq in new:
            c = frozenset(sq)
            if c in book.best or c in seen or not sess.fresh(sq):
                continue
            seen.add(c)
            fresh.append(sq)
        if not fresh:
            break
        got = sess.run(fresh, "구성", cap=min(G_ROUND - used, sess.left - reserve))
        if not got:
            break
        used += got
    return used


def do_kick(sess: Any, rng: random.Random, burst: Mapping[str, str], cap: int) -> set[frozenset] | None:
    """킥: 전체 최선 5덱에서 덱 2개를 풀고, 푼 니케 + 어느 덱에도 없는 니케로 구조 틀 무작위 스쿼드 2개를 새로 지어 평가한다.
    남긴 3덱 + 새 2덱이 새 계보다."""
    best = [sq for _, sq in sess.pack()[1]]
    if len(best) < 5 or cap < KICK_DECKS:
        return None
    drop = set(rng.sample(range(len(best)), KICK_DECKS))
    keep = [d for i, d in enumerate(best) if i not in drop]
    avail = [n for n in sess.acct.names if n not in {m for d in keep for m in d}]
    new: list[tuple] = []
    for _ in range(KICK_DECKS):
        sq = None
        for _t in range(200):
            cand = struct_squad(avail, Counter(), rng, burst)
            if cand is None:
                break
            if frozenset(cand) in sess.book.best or not sess.fresh(cand):
                continue
            sq = cand
            break
        if sq is None:
            return None
        new.append(sq)
        avail = [n for n in avail if n not in sq]
    sess.run(new, "킥", cap=cap)
    return {frozenset(d) for d in keep + new}


# ---------------------------------------------------------------- 기법

def run_method(acct: Account10 | Any, method: str, budget: int, ev: Any, pre: Mapping[str, Any] | None = None,
               pool: int | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    pool = getattr(acct, "pool", 60) if pool is None else pool
    fitf = fit_for(pool)
    burst = BURST_ALL
    start, esc = method.split("+")[0], method.endswith("+E")
    sess = R9.Session(acct, ev, budget)
    t0, sims0 = time.time(), ev.sim_count
    reserve = budget // 8
    tag = f"{acct.id}-P{pool}"
    if start == "K":
        order = R9.ranker_order(acct.owned)
        players = [R9.transplant([R9.RK_SQ[j] for j in R9.RANKERS["players"][i]["squads"]], acct.owned)
                   for i in order[:R9.K_RANKERS]]
        sess.run([d for decks in players for d in decks], "옮기기", cap=budget - reserve)
    elif start in ("R", "G"):
        sess.run(design(acct.names, burst, random.Random(f"exp10-design-{tag}")), "설계", cap=budget - reserve)
        if start == "G":
            construct(sess, reserve, fitf, burst, random.Random(f"exp10-construct-{tag}"))
    elif start == "P":
        if pre is None:
            raise ValueError("P · P+E에는 공유 사전 계산(precompute)이 필요하다")
        decks = [d for s in pre["sets"] for d in transplant_coef([tuple(x) for x in s], acct.owned, pre["coef"], burst)]
        sess.run(decks, "옮기기", cap=budget - reserve)
    else:
        raise ValueError(method)
    p0 = sess.pack()
    start_rec = {"evals": sess.used, "pack": p0[0]}
    history = [{"evals": sess.used, "pack": p0[0], "kick": False}]
    lineage: set[frozenset] | None = None
    lin_val = p0[0]
    kicks: list[dict[str, Any]] = []
    stalled = False
    while sess.left > reserve:
        kicked = False
        if esc and stalled:
            stalled = False
            best_now, used0 = sess.pack()[0], sess.used
            lin = do_kick(sess, random.Random(f"exp10-kick-{tag}-{method}-{len(kicks) + 1}"), burst,
                          cap=sess.left - reserve)
            if lin is None:
                break
            kicks.append({"evals": used0, "best": best_now})
            lineage, kicked = lin, True
            lin_val = lineage_pack(sess, lineage)
            if sess.left <= reserve:
                history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
                break
        n = min(ROUND, sess.left - reserve)
        pick = local_round(sess, n, lineage, fitf)
        if not pick or not sess.run(pick, f"탐색 {len(history)}", cap=n):
            if esc and not kicked:
                stalled = True
                continue
            if kicked:
                history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": True})
            break
        history.append({"evals": sess.used, "pack": sess.pack()[0], "kick": kicked})
        cur = lineage_pack(sess, lineage)
        if esc and cur <= lin_val + 1e-9:
            stalled = True
        lin_val = cur
    pre_order = {"evals": sess.used, "pack": sess.pack()[0]}
    for i, k in enumerate(kicks):
        nxt = kicks[i + 1]["best"] if i + 1 < len(kicks) else pre_order["pack"]
        k["improved"] = nxt > k["best"] + 1e-9
    best = sess.pack()
    tops = [sq for _, sq in best[1]] + [sq for _, sq in sorted(sess.book.best.values(), reverse=True)[:R9.ORDER_TOP]]
    orders = list(dict.fromkeys(p for sq in dict.fromkeys(tops) for p in R2.distinct_orders(sq, burst)
                                if sess.fresh(p)))
    sess.run(orders, "순서")
    final = sess.pack()
    history.append({"evals": sess.used, "pack": final[0], "kick": False})
    fsq = [sq for _, sq in final[1]]
    alt = R9.pack_vals(sess.book.best, avoid=[{frozenset(sq) for sq in fsq}])
    alt20 = pack_alt20(sess.book.best, fsq)
    summ = {"scenario": acct.id, "name": acct.name, "pool": pool, "method": method, "budget": budget,
            "evals": sess.used, "errors": sum(r["error"] is not None for r in sess.records),
            "start": start_rec, "history": history, "pre_order": pre_order, "kicks": kicks,
            "final": pack_dict(final), "alt": pack_dict(alt, fsq), "alt20": pack_dict(alt20, fsq),
            "sims_during": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1)}
    return summ, sess.records, sess


def precompute(pool: int, ev: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """공유 사전 계산: 전원 보유 · 상 계정에서 G+E 5,000평가 → 덱 2개 이하만 공유하는 최선 5덱 8벌 + 니케 계수."""
    acct = Account10(pre_scenario(), pool=pool, rankerless=True)
    t0, sims0 = time.time(), ev.sim_count
    summ, recs, sess = run_method(acct, "G+E", PRE_BUDGET, ev, pool=pool)
    sets, totals, avoid = [], [], []
    for _ in range(PRE_SETS):
        v, ch = R9.pack_vals(sess.book.best, avoid=avoid)
        if not ch:
            break
        sets.append([list(sq) for _, sq in ch])
        totals.append(v)
        avoid.append({frozenset(sq) for _, sq in ch})
    score = fit_for(pool)(sess.book, acct.names)
    base = score(frozenset())
    coef = {n: score(frozenset([n])) - base for n in acct.names}
    out = {"pool": pool, "budget": PRE_BUDGET, "evals": sess.used, "sims": ev.sim_count - sims0,
           "seconds": round(time.time() - t0, 1), "sets": sets, "set_totals": totals, "coef": coef,
           "final": summ["final"], "history": summ["history"], "kicks": summ["kicks"]}
    return out, recs


# ---------------------------------------------------------------- 실행 명령

def run_name(sid: str, pool: int, method: str, budget: int) -> str:
    return f"{sid}_P{pool}_{method}_{budget}"


def write_run(out: Path, name: str, summ: Mapping[str, Any], recs: Sequence[Mapping[str, Any]]) -> None:
    with gzip.open(out / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"{name}.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_pre(d: Path, pool: int) -> dict[str, Any]:
    return json.loads((d / f"precompute_P{pool}.json").read_text(encoding="utf-8"))


def cmd_precompute(args: argparse.Namespace) -> int:
    from nikke_opt.evaluator import make_evaluator
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"precompute_P{args.pool}.json"
    if path.exists():
        print(f"이미 있다: {path}", file=sys.stderr)
        return 0
    ev = make_evaluator()
    with ev:
        out, recs = precompute(args.pool, ev)
        out["evaluator"] = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
    with gzip.open(args.out / f"precompute_P{args.pool}.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pool": args.pool, "evals": out["evals"], "sims": out["sims"], "s": out["seconds"],
                      "best": round(out["final"]["total"], 2), "sets": [round(t, 1) for t in out["set_totals"]]},
                     ensure_ascii=False))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    scs = scenarios(args.set)
    if args.only:
        want = set(args.only.split(","))
        scs = [s for s in scs if s["id"] in want]
    methods = args.methods.split(",")
    assert all(m in METHODS for m in methods), methods
    budgets = [int(b) for b in args.budgets.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    pre = load_pre(args.pre or args.out, args.pool) if any(m.startswith("P") for m in methods) else None
    tasks = [(s, m, b) for b in sorted(budgets, reverse=True) for s in scs for m in methods
             if not (args.out / f"{run_name(s['id'], args.pool, m, b)}.json").exists()]
    from nikke_opt.evaluator import make_evaluator
    ev = make_evaluator()
    t0 = time.time()
    lock = threading.Lock()

    def work(task):
        s, m, b = task
        acct = Account10(s, pool=args.pool, rankerless=m in RANKERLESS)
        summ, recs, _ = run_method(acct, m, b, ev, pre=pre if m.startswith("P") else None)
        name = run_name(s["id"], args.pool, m, b)
        write_run(args.out, name, summ, recs)
        with lock:
            print(json.dumps({"run": name, "pack": round(summ["final"]["total"], 2), "evals": summ["evals"],
                              "kicks": len(summ["kicks"]), "s": summ["seconds"], "t": round(time.time() - t0),
                              "sims": ev.sim_count}, ensure_ascii=False), flush=True)

    with ev:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in [pool.submit(work, t) for t in tasks]:
                f.result()
        print(f"실행 {len(tasks)}개 · 시뮬 {ev.sim_count}회 · 캐시 {ev.cache_hits}회 · {time.time() - t0:.0f}초 · "
              f"평가기 {ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}", file=sys.stderr)
    return 0


def cmd_import_k(args: argparse.Namespace) -> int:
    """실험 9 L0k 기록 → K(P60) 요약. alt20은 평가 기록에서 다시 조립한다."""
    args.out.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (args.exp9 / f"{args.set}_summary.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    rows = [r for r in rows if r["method"] == "L0k"]
    want = {r["run"] for r in rows}
    recs: dict[str, list[dict[str, Any]]] = {w: [] for w in want}
    with gzip.open(args.exp9 / f"{args.set}_evals.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r["run"] in want:
                    recs[r["run"]].append(r)
    for r in rows:
        book = R9.book_of(recs[r["run"]])
        fin = R9.pack_vals(book)
        assert abs(fin[0] - r["final"]["total"]) < 1e-6, r["run"]
        fsq = [sq for _, sq in fin[1]]
        alt = R9.pack_vals(book, avoid=[{frozenset(sq) for sq in fsq}])
        h = r["history"]
        summ = {"scenario": r["scenario"], "name": r["name"], "pool": 60, "method": "K", "budget": r["budget"],
                "evals": r["evals"], "errors": r["errors"], "start": dict(h[0]),
                "history": [dict(x, kick=False) for x in h], "pre_order": dict(h[-2]), "kicks": [],
                "final": pack_dict(fin), "alt": pack_dict(alt, fsq), "alt20": pack_dict(pack_alt20(book, fsq), fsq),
                "sims_during": r["sims_during"], "seconds": r["seconds"], "source": f"실험 9 {r['run']}"}
        name = run_name(r["scenario"], 60, "K", r["budget"])
        (args.out / f"{name}.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"K {len(rows)}개를 옮겼다 → {args.out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precompute")
    p.add_argument("--pool", type=int, choices=(60, 177), required=True)
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("search")
    s.add_argument("--set", choices=("dev", "val"), required=True)
    s.add_argument("--pool", type=int, choices=(60, 177), default=60)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pre", type=Path)
    s.add_argument("--methods", default=",".join(NEW_METHODS))
    s.add_argument("--budgets", default=",".join(map(str, BUDGETS)))
    s.add_argument("--only")
    s.add_argument("--workers", type=int, default=4)
    k = sub.add_parser("import-k")
    k.add_argument("--set", choices=("dev", "val"), default="val")
    k.add_argument("--exp9", type=Path, default=EXP9 / "run_log")
    k.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"precompute": cmd_precompute, "search": cmd_search, "import-k": cmd_import_k}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
