"""실험 42 판 — 실험 10 `run_method`(G+E)에 끼우는 규칙 없는 부품과 묶음 단위 라운드. README §1단계.

- **R:** 구조 규칙을 쓰던 네 곳(설계 `design` · 구성 `greedy_squads` · 킥 `do_kick` · 이웃 `S4.neighbors` / `S4.pack_moves`)을
  규칙 없는 판으로 바꾼다. 스쿼드 순서는 기본 순서(실험 41 `base_order`)로 둔다 — 구성 탐색은 순서를 다루지 않는다.
- **P:** R + 라운드 고르기를 「가격 기반 후보」로: 지금까지 잰 구성으로 묶은 문제의 니케 가격 λ(실험 9 `_pack_lagrange`)를 구하고,
  대리 모델 예측 − Σλ가 큰 구성을 빔 탐색으로 만든다.
- **L:** R + 라운드 고르기를 「덱 둘 풀어 다시 짜기」로.

인터페이스: `patched(arm)` 문맥 안에서 `R10.run_method(acct, "G+E", …)`를 부른다. 판 수치는 `PARAMS`(개발 시즌에서만 정한다).
"""

from __future__ import annotations

import contextlib
import random
import sys
from collections import Counter
from itertools import combinations
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

R41 = sys.modules["run41"]
R10, R9 = R41.R10, R41.R9
S4 = R9.S4
base_order = R41.base_order

ARMS = ("base", "R", "P", "L", "P50", "PL")
PARAMS: dict[str, Any] = {
    "first_beam": 18,     # R 구성: 첫 니케 후보 수(실험 10은 틀 6 × 3 = 18)
    "beam": 40,           # P · L 빔 폭
    "lns_pool": 60,       # L: 풀린 자리에서 만들 대리 모델 상위 구성 수
    "lns_pairs": 3,       # L: 덱 쌍마다 평가할 새 두 덱 후보 수
    "p50_share": 0.5,     # P50: 라운드 중 가격 후보 몫(나머지 R 라운드)
    "pl_price_share": 0.2,  # PL: 다시 짜기 후보 다음 가격 후보 몫(나머지 R 라운드)
}


# ---------------------------------------------------------------- R: 규칙 없는 부품

def design_free(names: Sequence[str], burst: Mapping[str, str], rng: random.Random, n: int | None = None,
                avoid: Iterable[frozenset] = ()) -> list[tuple[str, ...]]:
    """균형 무작위 설계(실험 10 `design`과 같은 크기 · 같은 균형 규칙) — 틀 없이 자리마다 지금까지 가장 적게 나온 니케(동점 무작위)."""
    names = sorted(names)
    n = len(names) * R10.DESIGN_MULT // 5 if n is None else n
    counts: Counter = Counter()
    seen = set(avoid)
    out: list[tuple[str, ...]] = []
    tries = 0
    while len(out) < n and tries < 50 * n + 100:
        tries += 1
        chosen: list[str] = []
        for _ in range(5):
            opts = [m for m in names if m not in chosen]
            lo = min(counts[m] for m in opts)
            chosen.append(rng.choice([m for m in opts if counts[m] == lo]))
        c = frozenset(chosen)
        if c in seen:
            continue
        seen.add(c)
        counts.update(chosen)
        out.append(base_order(chosen))
    return out


def greedy_free(avail: Iterable[str], score: Callable, burst: Mapping[str, str], rng: random.Random,
                beam: int = R10.G_BEAM) -> list[tuple[str, ...]]:
    """대리 모델 탐욕 구성(실험 10 `greedy_squads`의 틀 없는 판): 단일 점수 상위 first_beam명에서 시작해 증분 최대 니케를 더한다."""
    avail = sorted(avail)
    if len(avail) < 5:
        return []
    single = dict(zip(avail, R10.add_scores(score, [], avail)))
    firsts = sorted(avail, key=lambda m: (-single[m], m))[:PARAMS["first_beam"]]
    out = []
    for m0 in firsts:
        cur = [m0]
        while len(cur) < 5:
            opts = [m for m in avail if m not in cur]
            vals = R10.add_scores(score, cur, opts)
            cur.append(max(zip(vals, opts))[1])
        out.append(base_order(cur))
    return out


def kick_free(sess: Any, rng: random.Random, burst: Mapping[str, str], cap: int) -> set[frozenset] | None:
    """실험 10 `do_kick`과 같다(덱 2개를 풀고 새 무작위 스쿼드 2개) — 새 스쿼드는 남은 니케에서 틀 없이 고른다."""
    best = [sq for _, sq in sess.pack()[1]]
    if len(best) < 5 or cap < R10.KICK_DECKS:
        return None
    drop = set(rng.sample(range(len(best)), R10.KICK_DECKS))
    keep = [d for i, d in enumerate(best) if i not in drop]
    avail = sorted(n for n in sess.acct.names if n not in {m for d in keep for m in d})
    new: list[tuple] = []
    for _ in range(R10.KICK_DECKS):
        sq = None
        for _t in range(200):
            if len(avail) < 5:
                break
            cand = base_order(rng.sample(avail, 5))
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


def neighbors_free(squad: tuple, pool: Mapping[str, Any]) -> list[tuple]:
    """한 명 교체 — 같은 단계에 묶지 않는다."""
    out = []
    for n in squad:
        rest = [x for x in squad if x != n]
        for m in pool:
            if m not in squad:
                out.append(base_order(rest + [m]))
    return out


def pack_moves_free(decks: list[tuple], pool: Mapping[str, Any], score: Callable) -> list[tuple[float, list[tuple]]]:
    """실험 4 `pack_moves`의 규칙 없는 판: 쓰지 않은 니케로 한 명 교체 · 두 덱 사이 한 명씩 맞바꾸기(단계 무관)."""
    used = {n for d in decks for n in d}
    pred = {d: score(frozenset(d)) for d in decks}
    moves = []
    for d in decks:
        for n in d:
            rest = [x for x in d if x != n]
            for m in pool:
                if m not in used:
                    nd = base_order(rest + [m])
                    moves.append((score(frozenset(nd)) - pred[d], [nd]))
    for a, b in combinations(decks, 2):
        for n in a:
            for m in b:
                na = base_order([x for x in a if x != n] + [m])
                nb = base_order([x for x in b if x != m] + [n])
                gain = score(frozenset(na)) + score(frozenset(nb)) - pred[a] - pred[b]
                moves.append((gain, [na, nb]))
    return sorted(moves, key=lambda mv: -mv[0])


_R_LOCAL: Callable = R10.local_round   # P · L이 후보가 모자랄 때 쓰는 R의 라운드(실험 10 `local_round` + 규칙 없는 이웃)


# ---------------------------------------------------------------- 공용: 빔 탐색 · 니케 가격

def beam_comps(score: Any, avail: Sequence[str], price: Mapping[str, float] | None, width: int, k: int = 5
               ) -> list[tuple[float, frozenset]]:
    """대리 모델 예측 − Σ가격이 큰 k인 구성(빔 탐색). 반환: (감한 예측, 구성) 내림차순."""
    avail = sorted(avail)
    if len(avail) < k:
        return []
    pr = {n: (price or {}).get(n, 0.0) for n in avail}
    beam: list[tuple[float, tuple]] = [(0.0, ())]
    for depth in range(k):
        nxt: dict[frozenset, float] = {}
        for _, cur in beam:
            opts = [m for m in avail if m not in cur]
            if not opts:
                continue
            vals = R10.add_scores(score, list(cur), opts)
            base_p = sum(pr[x] for x in cur)
            for v, m in zip(vals, opts):
                c = frozenset(cur + (m,))
                r = v - base_p - pr[m]
                if r > nxt.get(c, float("-inf")):
                    nxt[c] = r
        beam = [(r, tuple(sorted(c))) for c, r in sorted(nxt.items(), key=lambda kv: (-kv[1], sorted(kv[0])))[:width]]
    return [(r, frozenset(c)) for r, c in beam]


def nikke_prices(book: Mapping[frozenset, tuple[float, tuple]], names: Sequence[str], lb: float, k: int = 5) -> dict[str, float]:
    """잰 구성으로 묶는 문제(겹치지 않는 k덱 합 최대)의 니케 가격 λ ≥ 0 — 실험 9 `_pack_lagrange`(쌍대 상한을 lb 쪽으로 줄이는 λ).
    구성의 값 − Σλ > 0이면 그 구성이 묶음을 늘릴 수 있다(열 생성의 감한 값)."""
    comps = list(book)
    if len(comps) < k:
        return {n: 0.0 for n in names}
    ni = {n: i for i, n in enumerate(names)}
    vs = [book[c][0] for c in comps]
    inc = np.array([sorted(ni[x] for x in c) for c in comps], dtype=np.int64)
    lam = R9._pack_lagrange(vs, inc, len(names), k, inc.shape[1], lb)
    return {n: float(lam[i]) for n, i in ni.items()}


def _current(sess: Any, lineage: set[frozenset] | None) -> tuple[float, list[tuple[float, tuple]], dict]:
    book = sess.book.best if lineage is None else {c: v for c, v in sess.book.best.items() if c in lineage}
    t, d = R9.pack_vals(book)
    return t, d, book


# ---------------------------------------------------------------- P: 가격 기반 후보

def price_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable) -> list[tuple]:
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    total, _, book = _current(sess, lineage)
    price = nikke_prices(book, acct.names, total)
    cands = beam_comps(score, acct.names, price, PARAMS["beam"] * 3)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    for _, c in cands:
        if len(pick) >= n:
            break
        sq = base_order(c)
        if c in sess.book.best or c in seen or not sess.fresh(sq):
            continue
        seen.add(c)
        pick.append(sq)
    if len(pick) < n:                                          # 빔이 모자라면 R의 이웃으로 채운다
        for sq in _R_LOCAL(sess, n - len(pick), lineage, fitf):
            if frozenset(sq) not in seen:
                seen.add(frozenset(sq))
                pick.append(sq)
    if lineage is not None:
        lineage.update(frozenset(s) for s in pick)
    return pick[:n]


# ---------------------------------------------------------------- L: 덱 둘 풀어 다시 짜기

def lns_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable) -> list[tuple]:
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    _, decks, _ = _current(sess, lineage)
    if len(decks) < 5:
        return _R_LOCAL(sess, n, lineage, fitf)
    props: list[tuple[float, list[frozenset]]] = []
    for i, j in combinations(range(5), 2):
        keep = [d for q, (_, d) in enumerate(decks) if q not in (i, j)]
        used = {x for d in keep for x in d}
        avail = [m for m in acct.names if m not in used]
        top = beam_comps(score, avail, None, PARAMS["lns_pool"])
        pairs = []
        for (ra, a), (rb, b) in combinations(top, 2):
            if not a & b:
                pairs.append((ra + rb, a, b))
        pairs.sort(key=lambda t: -t[0])
        old = decks[i][0] + decks[j][0]
        for g, a, b in pairs[:PARAMS["lns_pairs"]]:
            props.append((g - old, [a, b]))
    props.sort(key=lambda t: -t[0])
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    for _, cs in props:
        for c in cs:
            sq = base_order(c)
            if len(pick) >= n:
                break
            if c in sess.book.best or c in seen or not sess.fresh(sq):
                continue
            seen.add(c)
            pick.append(sq)
    if len(pick) < n:
        for sq in _R_LOCAL(sess, n - len(pick), lineage, fitf):
            if frozenset(sq) not in seen:
                seen.add(frozenset(sq))
                pick.append(sq)
    if lineage is not None:
        lineage.update(frozenset(s) for s in pick)
    return pick[:n]


# ---------------------------------------------------------------- 개발 변형(1단계 첫 재생 뒤, 개발 시즌에서만 정함)
# 첫 재생(PARAMS 처음 값): P는 라운드 100을 가격 후보로만 채워 국소 다듬기(R 이웃 · 5덱 고치기)가 없다 — S36에서 멈춤(99% 1/4).
# L은 다시 짜기 후보(≤ 60) + R 이웃이라 S36 4/4지만 S39에서 99.3% 국소 최적에 머문다(가격 후보가 S39 4/4).
# P50 = 가격 후보 몫을 절반으로, 나머지 R 라운드. PL = 다시 짜기 후보 + 가격 후보 몫 + 나머지 R 라운드.

def _price_cands(sess: Any, lineage: set[frozenset] | None, score: Callable) -> list[tuple[float, frozenset]]:
    total, _, book = _current(sess, lineage)
    price = nikke_prices(book, sess.acct.names, total)
    return beam_comps(score, sess.acct.names, price, PARAMS["beam"] * 3)


def _lns_props(sess: Any, lineage: set[frozenset] | None, score: Callable) -> list[tuple[float, list[frozenset]]]:
    _, decks, _ = _current(sess, lineage)
    if len(decks) < 5:
        return []
    props: list[tuple[float, list[frozenset]]] = []
    for i, j in combinations(range(5), 2):
        keep = [d for q, (_, d) in enumerate(decks) if q not in (i, j)]
        used = {x for d in keep for x in d}
        top = beam_comps(score, [m for m in sess.acct.names if m not in used], None, PARAMS["lns_pool"])
        pairs = sorted(((ra + rb, a, b) for (ra, a), (rb, b) in combinations(top, 2) if not a & b), key=lambda t: -t[0])
        old = decks[i][0] + decks[j][0]
        props += [(g - old, [a, b]) for g, a, b in pairs[:PARAMS["lns_pairs"]]]
    return sorted(props, key=lambda t: -t[0])


def mix_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable, price_share: float, lns: bool) -> list[tuple]:
    """다시 짜기 후보(lns이면, 전부) → 가격 후보(라운드의 price_share 몫까지) → 나머지 R 라운드."""
    score = fitf(sess.book, sess.acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()

    def take(c: frozenset) -> bool:
        sq = base_order(c)
        if len(pick) >= n or c in sess.book.best or c in seen or not sess.fresh(sq):
            return False
        seen.add(c)
        pick.append(sq)
        return True

    if lns:
        for _, cs in _lns_props(sess, lineage, score):
            for c in cs:
                take(c)
    k, got = int(round(n * price_share)), 0
    for _, c in _price_cands(sess, lineage, score):
        if got >= k or len(pick) >= n:
            break
        got += take(c)
    if len(pick) < n:
        for sq in _R_LOCAL(sess, n - len(pick), lineage, fitf):
            if frozenset(sq) not in seen:
                seen.add(frozenset(sq))
                pick.append(sq)
    if lineage is not None:
        lineage.update(frozenset(s) for s in pick)
    return pick[:n]


def p50_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable) -> list[tuple]:
    return mix_round(sess, n, lineage, fitf, PARAMS["p50_share"], lns=False)


def pl_round(sess: Any, n: int, lineage: set[frozenset] | None, fitf: Callable) -> list[tuple]:
    return mix_round(sess, n, lineage, fitf, PARAMS["pl_price_share"], lns=True)


ROUNDS: dict[str, Callable] = {"P": price_round, "L": lns_round, "P50": p50_round, "PL": pl_round}


# ---------------------------------------------------------------- 끼우기

@contextlib.contextmanager
def patched(arm: str):
    """판의 부품을 실험 10 · 4 모듈에 끼운다(문맥이 끝나면 되돌린다). base는 그대로."""
    if arm not in ARMS:
        raise ValueError(arm)
    saved = {(R10, "design"): R10.design, (R10, "greedy_squads"): R10.greedy_squads, (R10, "do_kick"): R10.do_kick,
             (S4, "neighbors"): S4.neighbors, (S4, "pack_moves"): S4.pack_moves, (R10, "local_round"): R10.local_round}
    try:
        if arm != "base":
            R10.design, R10.greedy_squads, R10.do_kick = design_free, greedy_free, kick_free
            S4.neighbors, S4.pack_moves = neighbors_free, pack_moves_free
        if arm in ROUNDS:
            R10.local_round = ROUNDS[arm]
        yield
    finally:
        for (mod, name), fn in saved.items():
            setattr(mod, name, fn)
