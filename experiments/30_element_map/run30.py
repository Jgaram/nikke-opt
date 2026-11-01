"""실험 30 — 속성별 사전 계산 5덱 지도: 기준선(B) 대 넓게 찾기(W) · 코어 30 재평가(README §절차).

    source .cache/evaluators.env && python experiments/30_element_map/run30.py run --element 작열
        → run_log/<속성>/B_s0.jsonl.gz · B_s1.jsonl.gz · W.jsonl.gz · core30.jsonl.gz · summary.json
    python experiments/30_element_map/run30.py analyze      → results.md · analysis.json (시뮬 0)
    source .cache/evaluators.env && python experiments/30_element_map/run30.py corecheck --season 40,34
        → run_log/corecheck_S40.json (실험 22 코어 없음 기록 상위 → 코어 30 재평가, 관리자)

- 계정: SSR 177명 전원 보유 · 상(사전 계산 계정), 보스 = 기본 적 + 속성(`enemy.code`), 코어 없음. 운용은 기본 레이어 고정.
- B = 시드 s0 · s1 각 G+E 12,500평가(실험 12 PB15와 같은 절차, 예산만 12,500), 기록 합치기.
- W = 같은 두 시드의 앞 6,250평가 기록(B 기록 앞부분, 시뮬 0) + 넓게 찾기 12,500평가:
  A 순서 다듬기 → 큰 분류 블록(1,000평가: 근처 탐색 875 + 순서 125)을 되풀이한다.
- 지도(분석): 기록마다 같은 탐욕 고르기 — 1번 = 최선, 다음 = 앞 대표 모두와 J ≤ 0.2인 최선(실험 28 `pick_far`).
"""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
ROOT = EXPS.parent
LOG = HERE / "run_log"
sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


T28 = sys.modules.get("tree28") or _load("tree28", EXPS / "28_plan_tree" / "tree28.py")
R12 = sys.modules.get("run12") or _load("run12", EXPS / "12_precompute_seeds" / "run12.py")
R26 = sys.modules.get("run26") or _load("run26", EXPS / "26_alt_local" / "run26.py")
R9, P24, SIM = T28.R9, T28.P24, T28.SIM
R11, R10, S4 = R12.R11, R12.R10, R12.S4
R2 = R10.R2
E8 = 1e8

# ---------------------------------------------------------------- 사전 등록한 값(README)
ELEMENTS = ("전격", "풍압", "철갑", "수냉", "작열")
SEEDS = (0, 1)
SEED_BUDGET = 12500                 # B: 시드마다
PREFIX = SEED_BUDGET // 2           # W: 시드마다 B 기록 앞 6,250평가
W_BUDGET = SEED_BUDGET              # W 넓게 찾기(새 평가)의 계획값. 본 실행은 w_budget_of() = B가 실제로 쓴 평가 수 − 앞부분
                                    # (2026-11-01 변경: B 시드가 끝 순서 다듬기에서 예산을 다 쓰지 않고 약 11,000에서 끝났다)
A_ORDER = 1250                      # W 첫 블록: A 순서 다듬기 상한
BLOCK, BLOCK_ORDER = 1000, 125      # 큰 분류 블록: 근처 탐색 875 + 그 대표 순서 125(실험 26 · 27과 같다)
BLOCK_MIN = 300                     # 남은 예산이 이보다 적으면 블록을 열지 않는다
ROUND = 100
FIX_SHARE = R26.FIX_SHARE           # 0.7: 5덱 고치기 몫(나머지는 대표 덱 이웃)
THETA = 0.2                         # 큰 분류 대표끼리 J ≤ 0.2
NEW_MIN = 0.90                      # 새 큰 분류 후보(탐색 전)가 지금 최선의 90% 미만이면 새로 열지 않는다
MAX_REPS = 10                       # 지도 대표 최대(A 포함)
GOOD, LOW = 0.97, 0.95
PACK_LIMIT = 120.0                  # 지도(분석) pick_far 제한 시간(초)
ROUND_LIMIT = 30.0                  # W 탐색 중 고르기 제한 시간(초) — 넘으면 찾은 해(직전 대표보다 낮으면 직전 대표)
CORE_N = 2000                       # 코어 30 재평가 후보 수: 지도 대표 덱 + 대표 5덱의 덱 자리마다 바꿔 넣을 구성(core_candidates)
CORE_PX = 30
CORE_EXTRA = 2000                   # corecheck: 재평가 뒤 코어 30에서 이어 찾기(국소 탐색 + 끝 1/8 순서 다듬기)
EXP22 = EXPS / "22_ranker_check"


def options(element: str, core: int = 0) -> dict[str, Any]:
    enemy: dict[str, Any] = {"code": element}
    if core:
        enemy["core_px"] = core
    return {"enemy": enemy}


def account(element: str, seed: int, core: int = 0) -> Any:
    acct = R12.pre_account(seed)          # 실험 11 · 12 사전 계산 계정(시드 k ≥ 1이면 id = pre-s<k>)
    acct.options = options(element, core)
    return acct


def edir(element: str) -> Path:
    return LOG / element


def write_recs(path: Path, recs: Sequence[Mapping[str, Any]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_recs(path: Path) -> list[dict[str, Any]]:
    return R9.load_records(path)


def book_of(recs: Sequence[Mapping[str, Any]], book: dict | None = None) -> dict[frozenset, tuple[float, tuple]]:
    best = {} if book is None else book
    for r in recs:
        if r.get("total_damage") is None:
            continue
        sq, v = tuple(r["squad"]), r["total_damage"] / E8
        c = frozenset(sq)
        if c not in best or v > best[c][0]:
            best[c] = (v, sq)
    return best


# ---------------------------------------------------------------- 지도(탐욕 고르기)

def pick_far30(vals: Mapping[frozenset, tuple[float, tuple]], book: Mapping, refs: Sequence[Sequence[tuple]],
             theta: float = THETA, limit: float = PACK_LIMIT) -> dict[str, Any]:
    """refs 모두와 J ≤ θ(각 기준과의 공유 쌍 ≤ 예산)인 겹치지 않는 5덱 중 합 최대 — 기준마다 예산을 따로 지키는 분기 한정.
    값 순 DFS, 상한 = 남은 후보 중 앞 r개 값 합. 제한 시간을 넘기면 찾은 해를 쓰고 exact = False.
    실험 28 `pick_far` 사본 — 탐색 순서 · 해는 같고, 제한 시간을 64단계마다(상한 계산 안에서도 4,096후보마다) 확인한다.
    원본은 4,096단계마다 확인해, 후보가 1만 개 넘는 사전 계산 기록에서는 제한 시간을 몇 분씩 넘겼다(실험 30 0단계 · 시운전)."""
    b = P24.budget_of(theta)
    costs = [P24.pair_cost(book, [frozenset(q) for q in r]) for r in refs]
    cands = sorted(((v, sq, c, tuple(ci[c] for ci in costs)) for c, (v, sq) in vals.items()
                    if all(ci[c] <= b for ci in costs)), key=lambda t: (-t[0], t[1]))
    bit: dict[str, int] = {}
    masks = []
    for _, _, c, _ in cands:
        m = 0
        for x in c:
            m |= 1 << bit.setdefault(x, len(bit))
        masks.append(m)
    vs = [t[0] for t in cands]
    cs = [t[3] for t in cands]
    n, k = len(cands), 5
    best = {"total": float("-inf"), "pick": None}
    deadline = time.monotonic() + limit
    state = {"timeout": False, "nodes": 0}

    def ok(i: int, used: int, spent: tuple) -> tuple | None:
        if masks[i] & used:
            return None
        ns = tuple(a + c for a, c in zip(spent, cs[i]))
        return None if any(x > b for x in ns) else ns

    # 시작 해: 앞쪽 후보마다 탐욕 완성
    for first in range(min(n, 200)):
        used, spent, total, pick = 0, tuple(0 for _ in refs), 0.0, []
        for j in range(first, n):
            ns = ok(j, used, spent)
            if ns is None:
                continue
            used, spent, total = used | masks[j], ns, total + vs[j]
            pick.append(j)
            if len(pick) == k:
                break
        if len(pick) == k and total > best["total"]:
            best["total"], best["pick"] = total, pick

    # 값 − μ·비용 순서로도 채워 본다(값 순 탐욕은 두 예산 안에서 못 채우기 쉽다). 합은 후보 번호 순으로 더한다
    for mu in (0.5, 1, 2, 4, 8, 16):
        order = sorted(range(n), key=lambda j: (-(vs[j] - mu * sum(cs[j])), j))
        for first in range(min(n, 50)):
            used, spent, pick = 0, tuple(0 for _ in refs), []
            for j in order[first:]:
                ns = ok(j, used, spent)
                if ns is None:
                    continue
                used, spent = used | masks[j], ns
                pick.append(j)
                if len(pick) == k:
                    break
            if len(pick) == k:
                total = 0.0
                for j in sorted(pick):
                    total += vs[j]
                if total > best["total"]:
                    best["total"], best["pick"] = total, sorted(pick)

    def bound(i0: int, r: int, used: int, spent: tuple) -> float:
        """i0 이후에서, 지금 쓴 니케와 겹치지 않고 혼자서는 예산 안인 후보의 앞 r개 값 합(서로 겹침은 무시)."""
        out, got = 0.0, 0
        for j in range(i0, n):
            if (j - i0) % 4096 == 4095 and time.monotonic() > deadline:
                state["timeout"] = True
                return float("-inf")
            if ok(j, used, spent) is not None:
                out += vs[j]
                got += 1
                if got == r:
                    return out
        return float("-inf")

    def dfs(i0: int, r: int, used: int, spent: tuple, total: float, pick: list) -> None:
        if state["timeout"]:
            return
        if r == 0:
            if total > best["total"]:
                best["total"], best["pick"] = total, list(pick)
            return
        if total + bound(i0, r, used, spent) <= best["total"]:
            return
        for i in range(i0, n - r + 1):
            if total + sum(vs[i:i + r]) <= best["total"]:
                return
            ns = ok(i, used, spent)
            if ns is None:
                continue
            state["nodes"] += 1
            if state["nodes"] % 64 == 0 and time.monotonic() > deadline:
                state["timeout"] = True
                return
            pick.append(i)
            dfs(i + 1, r - 1, used | masks[i], ns, total + vs[i], pick)
            pick.pop()
            if state["timeout"]:
                return

    dfs(0, k, 0, tuple(0 for _ in refs), 0.0, [])
    if best["pick"] is None:
        return {"found": False, "exact": not state["timeout"]}
    d = [(vs[i], cands[i][1]) for i in best["pick"]]
    return {"found": True, "total": best["total"], "decks": d, "exact": not state["timeout"], "nodes": state["nodes"]}


def class_map(book: Mapping[frozenset, tuple[float, tuple]], limit: float | None = None,
              max_reps: int | None = None, low: float = LOW) -> dict[str, Any]:
    """1번 = 최선, 다음 = 앞 대표 모두와 J ≤ θ인 겹치지 않는 5덱 중 합 최대. 최선의 low 아래거나 못 찾으면 멈춘다."""
    limit = PACK_LIMIT if limit is None else limit
    max_reps = MAX_REPS if max_reps is None else max_reps
    t0 = time.time()
    a_total, a_decks = R9.pack_vals(book)
    reps = [{"total": a_total, "decks": [list(q) for _, q in a_decks], "exact": True}]
    while len(reps) < max_reps:
        refs = [[tuple(q) for q in r["decks"]] for r in reps]
        got = pick_far30(book, book, refs, theta=THETA, limit=limit)
        if not got["found"]:
            break
        rec = {"total": got["total"], "decks": [list(q) for _, q in got["decks"]], "exact": got["exact"]}
        if got["total"] < low * a_total:
            rec["below"] = True
            reps.append(rec)
            break
        reps.append(rec)
    plans = [r["decks"] for r in reps]
    for i, r in enumerate(reps):
        r["ratio"] = r["total"] / a_total
        r["jmax"] = max((SIM.pair_jaccard(plans[i], plans[j]) for j in range(len(plans)) if j != i), default=None)
    return {"comps": len(book), "best": a_total, "reps": reps, "exact": all(r["exact"] for r in reps),
            "seconds": round(time.time() - t0, 1)}


def count_at(m: Mapping[str, Any], ref: float, good: float = GOOD) -> int:
    return sum(1 for r in m["reps"] if not r.get("below") and r["total"] >= good * ref - 1e-9)


# ---------------------------------------------------------------- W: 넓게 찾기

def within(decks: Sequence[Sequence[str]], refs: Sequence[Sequence[frozenset]], budget: int) -> bool:
    return all(R26.plan_cost(decks, r) <= budget for r in refs)


def pick_target(book: Mapping[frozenset, tuple[float, tuple]], refs: Sequence[Sequence[tuple]],
                prev: Sequence[Sequence[str]] | None, limit: float = ROUND_LIMIT) -> dict[str, Any]:
    """refs 모두와 J ≤ θ인 5덱 중 합 최대. 직전 대표(prev)가 지금 refs에도 가능한 해면, 시간 초과로 더 낮게 나올 때 직전 것을 쓴다
    (A가 새 최선으로 바뀌면 직전 대표가 새 A와 J > θ일 수 있다 — 그때는 쓰지 않는다)."""
    if prev and not within(prev, [[frozenset(q) for q in r] for r in refs], P24.budget_of(THETA)):
        prev = None
    if refs:
        p = pick_far30(book, book, refs, THETA, limit)
        out = {"found": p["found"], "exact": p.get("exact", False), "total": p.get("total", float("-inf")),
               "decks": [list(q) for _, q in p.get("decks", [])]}
    else:
        t, d = R9.pack_vals(book)
        out = {"found": True, "exact": True, "total": t, "decks": [list(q) for _, q in d]}
    if prev and all(frozenset(q) in book for q in prev):
        floor = 0.0
        for q in prev:
            floor += book[frozenset(q)][0]
        if not out["found"] or out["total"] < floor - 1e-12:
            out.update(found=True, total=floor, decks=[list(q) for q in prev])
    return out


def targeted_round(sess: Any, n: int, fitf: Any, refs: Sequence[Sequence[tuple]], prev: Sequence[Sequence[str]] | None
                   ) -> tuple[list[tuple], dict[str, Any]]:
    """실험 27 · 29 `targeted_round`와 같은 후보 만들기 — 고르기 · 고친 뒤 확인을 refs 전부로 한다."""
    book = sess.book.best
    p = pick_target(book, refs, prev)
    if not p["found"]:
        return [], p
    rs = [[frozenset(q) for q in r] for r in refs]
    b = P24.budget_of(THETA)
    decks = [tuple(book[frozenset(q)][1]) for q in p["decks"]]
    acct = sess.acct
    score = fitf(sess.book, acct.names)
    pick: list[tuple] = []
    seen: set[frozenset] = set()
    take = R9._take_factory(sess, pick, seen, n)
    got = 0
    for _, new in S4.pack_moves(decks, acct.owned, score):
        if got >= int(n * FIX_SHARE):
            break
        if within(R26.apply_move(decks, new), rs, b):
            got += take(new)
    used = {x for d in decks for x in d}
    cands = []
    for i, d in enumerate(decks):
        rest = decks[:i] + decks[i + 1:]
        for nb in S4.neighbors(d, {k: v for k, v in acct.owned.items() if k not in used or k in d}):
            if frozenset(nb) in book or not within(rest + [nb], rs, b):
                continue
            cands.append((score(frozenset(nb)) - score(frozenset(d)), nb))
    for _, nb in sorted(cands, reverse=True):
        if len(pick) >= n:
            break
        take([nb])
    return pick, p


def order_moves(sess: Any, decks: Sequence[Sequence[str]], extra_top: int = 0) -> list[tuple]:
    book = sess.book.best
    tops = [tuple(book[frozenset(q)][1]) for q in decks]
    if extra_top:
        tops += [sq for _, sq in sorted(book.values(), reverse=True)[:extra_top]]
    return list(dict.fromkeys(o for sq in dict.fromkeys(tops) for o in R2.distinct_orders(sq, R10.BURST_ALL) if sess.fresh(o)))


def plan_total(book: Mapping[frozenset, tuple[float, tuple]], decks: Sequence[Sequence[str]]) -> float:
    t = 0.0
    for q in decks:
        t += book[frozenset(q)][0]
    return t


def run_wide(acct: Any, ev: Any, prefix: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sess = R9.Session(acct, ev, W_BUDGET)
    R26.preload(sess, prefix)
    fitf = R10.fit_for(177)
    t0, sims0 = time.time(), ev.sim_count
    book = sess.book.best
    start = R9.pack_vals(book)
    # 블록 A: 최선 5덱 · 상위 구성 순서 다듬기(B의 시드 끝 순서 다듬기에 해당)
    sess.run(order_moves(sess, [q for _, q in start[1]], extra_top=R9.ORDER_TOP), "A 순서", cap=A_ORDER)
    a = pick_target(book, [], None)
    reps: list[list[list[str]]] = [a["decks"]]
    blocks: list[dict[str, Any]] = [{"kind": "A", "evals": sess.used, "best": a["total"]}]
    stalled: set[int] = set()     # 블록이 새 평가를 하나도 못 한 분류 — 다시 찾기에서 뺀다(2026-11-01 수정: 풍압에서 0평가 블록이 무한 반복)
    while sess.left >= BLOCK_MIN:
        a_total = R9.pack_vals(book)[0]
        reps[0] = pick_target(book, [], reps[0])["decks"]          # 최선이 바뀌었으면 A를 새 최선으로
        refs = [[tuple(q) for q in r] for r in reps]
        target, kind = None, None
        if len(reps) < MAX_REPS:
            cand = pick_target(book, refs, None)
            if cand["found"] and cand["total"] >= NEW_MIN * a_total:
                target, kind = len(reps), "new"
                reps.append(cand["decks"])
        if target is None:
            lows = sorted((plan_total(book, reps[i]) / a_total, i) for i in range(1, len(reps)))
            lows = [(r, i) for r, i in lows if r < GOOD and i not in stalled]
            if not lows:
                break
            target, kind = lows[0][1], "revisit"
        others = [[tuple(q) for q in reps[j]] for j in range(len(reps)) if j != target]
        before = plan_total(book, reps[target])
        used0, cap = sess.used, min(BLOCK, sess.left)
        prev = reps[target]
        while sess.used - used0 < cap - BLOCK_ORDER:
            n = min(ROUND, cap - BLOCK_ORDER - (sess.used - used0))
            pick, p = targeted_round(sess, n, fitf, others, prev)
            prev = p["decks"] if p["found"] else prev
            if not pick or not sess.run(pick, f"분류 {target} 탐색", cap=n):
                break
        p = pick_target(book, others, prev)
        sess.run(order_moves(sess, p["decks"]), f"분류 {target} 순서", cap=cap - (sess.used - used0))
        p = pick_target(book, others, p["decks"])
        reps[target] = p["decks"]
        if sess.used == used0:
            stalled.add(target)
        blocks.append({"kind": kind, "target": target, "evals": sess.used, "spent": sess.used - used0,
                       "before": before, "after": p["total"], "best": R9.pack_vals(book)[0], "exact": p["exact"]})
        print(json.dumps({"element": acct.options["enemy"]["code"], **{k: (round(v, 2) if isinstance(v, float) else v)
                                                                         for k, v in blocks[-1].items()}},
                         ensure_ascii=False), flush=True)
    summ = {"start": start[0], "blocks": blocks, "reps": reps, "evals": sess.used, "sims_during": ev.sim_count - sims0,
            "requests": len(sess.records), "seconds": round(time.time() - t0, 1),
            "errors": sum(r["error"] is not None for r in sess.records), "stalled": sorted(stalled)}
    return summ, sess.records


# ---------------------------------------------------------------- 실행

def slot_lists(book: Mapping[frozenset, tuple[float, tuple]], plans: Sequence[Sequence[Sequence[str]]]) -> list[list[frozenset]]:
    """대표 5덱마다 · 덱 자리마다: 나머지 4덱과 겹치지 않는 구성(그 자리의 원래 덱 제외)을 값 큰 순으로."""
    ranked = sorted(book, key=lambda c: (-book[c][0], book[c][1]))
    out = []
    for plan in plans:
        decks = [frozenset(q) for q in plan]
        for i in range(len(decks)):
            rest = frozenset().union(*(d for j, d in enumerate(decks) if j != i))
            out.append([c for c in ranked if c != decks[i] and not (c & rest)])
    return out


def core_candidates(nb: Mapping[frozenset, tuple[float, tuple]], maps: Sequence[Mapping[str, Any]], n: int = None) -> list[tuple]:
    """지도 대표 덱(먼저) + 대표 5덱의 덱 자리마다 바꿔 넣을 수 있는 구성을 자리끼리 돌아가며(값 큰 순) 합 n개(기본 CORE_N).
    대표 5덱이 모두 들어가므로 재평가 값으로 늘 5덱이 짜지고, 대표마다 덱 하나 바꾼 이웃이 함께 들어간다.
    0단계(pre_pack.md): 값 순 전체 상위 · 니케마다 돌아가며 상위 2,000으로는 코어 없음 값으로도 5덱이 안 짜지는 기록이 많았다.
    순서는 그 구성의 가장 좋은 배치 순서."""
    n = CORE_N if n is None else n
    plans = list(dict.fromkeys(tuple(tuple(q) for q in r["decks"]) for m in maps for r in m["reps"]))
    picks = list(dict.fromkeys(frozenset(q) for plan in plans for q in plan))
    seen = set(picks)
    lists = slot_lists(nb, plans)
    k = 0
    while len(picks) < n and any(k < len(x) for x in lists):
        for x in lists:
            if k < len(x) and x[k] not in seen:
                seen.add(x[k])
                picks.append(x[k])
                if len(picks) >= n:
                    break
        k += 1
    return [tuple(nb[c][1]) for c in picks[:max(n, 0)]]


def core_reeval(element: str, ev: Any, nb: Mapping[frozenset, tuple[float, tuple]], maps: Sequence[Mapping[str, Any]]
                ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """core_candidates(합 CORE_N)를 코어 30으로 다시 평가한다."""
    from nikke_opt.evaluator import EvalRequest
    todo = core_candidates(nb, maps)
    t0, sims0 = time.time(), ev.sim_count
    opts = options(element, CORE_PX)
    res = ev.evaluate([EvalRequest(list(q), boss=None, options=opts) for q in todo])
    recs = [{"squad": list(q), "total_damage": None if r.error else r.total_damage, "phase": "코어 30 재평가",
             "error": r.error, "cached": r.cached} for q, r in zip(todo, res)]
    return {"requests": len(todo), "sims": ev.sim_count - sims0, "seconds": round(time.time() - t0, 1)}, recs


PARTS = ("B_s0", "B_s1", "W", "core30")


def part_file(el: str, part: str) -> Path:
    return edir(el) / f"part_{part}.json"


def summary(el: str) -> dict[str, Any]:
    """부분별 기록(part_*.json)을 모은 속성 요약. 시뮬은 부분 합(같은 컨테이너 캐시 기준)."""
    out: dict[str, Any] = {"element": el}
    for part in PARTS:
        f = part_file(el, part)
        if f.exists():
            out[part] = json.loads(f.read_text(encoding="utf-8"))
    out["sims_total"] = sum(out[p]["sims"] for p in PARTS if p in out)
    return out


def w_budget_of(el: str, prefix_evals: int) -> int:
    """B와 W의 총평가를 같게: B 두 시드가 실제로 쓴 평가 수 합 − W 앞부분 평가 수(2026-11-01 변경, README §변경)."""
    return sum(json.loads(part_file(el, f"B_s{k}").read_text(encoding="utf-8"))["evals"] for k in SEEDS) - prefix_evals


def cmd_run(a: argparse.Namespace) -> int:
    """--part 순서: B_s0 · B_s1(서로 독립 — 프로세스 둘로 동시에 돌려도 된다) → W(B 둘 다 필요) → core30(B · W 필요)."""
    from nikke_opt.evaluator import make_evaluator
    el = a.element
    if el not in ELEMENTS:
        raise ValueError(f"속성은 {ELEMENTS} 중 하나: {el}")
    d = edir(el)
    d.mkdir(parents=True, exist_ok=True)
    parts = PARTS if a.part == "all" else tuple(a.part.split(","))
    seed_budget = a.seed_budget
    global W_BUDGET
    if a.w_budget is not None:
        W_BUDGET = a.w_budget

    def save(part: str, s: Mapping[str, Any]) -> None:
        part_file(el, part).write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"element": el, part: {k: v for k, v in s.items() if k not in ("blocks", "reps")}},
                         ensure_ascii=False), flush=True)

    with make_evaluator() as ev:
        evaluator = f"{ev.version.get('repo')} {str(ev.version.get('commit'))[:7]}"
        for part in parts:
            if part not in PARTS:
                raise ValueError(f"--part는 {PARTS} · all 중: {part}")
            if part_file(el, part).exists():
                continue
            sims0 = ev.sim_count
            if part.startswith("B_s"):
                k = int(part[3:])
                s, recs, _ = R10.run_method(account(el, k), "G+E", seed_budget, ev, pool=177)
                write_recs(d / f"{part}.jsonl.gz", recs)
                out = {"evals": s["evals"], "seconds": s["seconds"], "best": s["final"]["total"],
                       "errors": s["errors"], "kicks": len(s["kicks"]), "history": s["history"]}
            elif part == "W":
                prefix = [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")[:seed_budget // 2]]
                if a.w_budget is None:
                    W_BUDGET = w_budget_of(el, len(prefix))
                out, recs = run_wide(account(el, 0), ev, prefix)
                write_recs(d / "W.jsonl.gz", recs)
                out["prefix_evals"] = len(prefix)
            else:
                bm, wm = maps_of(el, seed_budget)
                out, recs = core_reeval(el, ev, book_of(all_recs(el, seed_budget)), [bm, wm])
                write_recs(d / "core30.jsonl.gz", recs)
            out.update(sims=ev.sim_count - sims0, evaluator=evaluator, seed_budget=seed_budget, w_budget=W_BUDGET)
            save(part, out)
    print(json.dumps({"element": el, "sims_total": summary(el)["sims_total"]}, ensure_ascii=False), flush=True)
    return 0


def arm_recs(el: str, arm: str, seed_budget: int = SEED_BUDGET) -> list[dict[str, Any]]:
    d = edir(el)
    if arm == "B":
        return [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")]
    return [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")[:seed_budget // 2]] + load_recs(d / "W.jsonl.gz")


def all_recs(el: str, seed_budget: int = SEED_BUDGET) -> list[dict[str, Any]]:
    d = edir(el)
    return [r for k in SEEDS for r in load_recs(d / f"B_s{k}.jsonl.gz")] + load_recs(d / "W.jsonl.gz")


def maps_of(el: str, seed_budget: int = SEED_BUDGET) -> tuple[dict[str, Any], dict[str, Any]]:
    cache = edir(el) / "maps.json"
    if cache.exists():
        m = json.loads(cache.read_text(encoding="utf-8"))
        if m.get("seed_budget") == seed_budget:
            return m["B"], m["W"]
    bm = class_map(book_of(arm_recs(el, "B", seed_budget)))
    wm = class_map(book_of(arm_recs(el, "W", seed_budget)))
    cache.write_text(json.dumps({"seed_budget": seed_budget, "B": bm, "W": wm}, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    return bm, wm


# ---------------------------------------------------------------- 코어 확인(실험 22 기록, 관리자)

class KnownEvaluator:
    """이미 아는 값(같은 평가기 · 같은 요청 options의 기록)은 시뮬 없이 돌려주고 나머지만 평가기에 묻는다."""

    def __init__(self, ev: Any, known: Mapping[tuple, int]):
        self.ev, self.known, self.version = ev, dict(known), ev.version
        self.known_hits = 0

    @property
    def sim_count(self) -> int:
        return self.ev.sim_count

    def evaluate(self, reqs: Sequence[Any]) -> list[Any]:
        from nikke_opt.evaluator import EvalResult
        out: list[Any] = [None] * len(reqs)
        ask = [i for i, r in enumerate(reqs) if tuple(r.squad) not in self.known]
        for i, r in enumerate(reqs):
            if tuple(r.squad) in self.known:
                out[i] = EvalResult(self.known[tuple(r.squad)], {}, cached=True)
                self.known_hits += 1
        if ask:
            for i, res in zip(ask, self.ev.evaluate([reqs[i] for i in ask])):
                out[i] = res
        return out


def continue_search(acct: Any, ev: Any, records: Sequence[Mapping[str, Any]], budget: int) -> tuple[dict[str, Any], list]:
    """기록을 넣고(시뮬 0) 그 위에서 국소 탐색(실험 10 `local_round`, 킥 없음) → 끝 1/8 순서 다듬기."""
    sess = R9.Session(acct, ev, budget)
    R26.preload(sess, records)
    fitf = R10.fit_for(177)
    reserve = budget // 8
    start = R9.pack_vals(sess.book.best)[0]
    while sess.left > reserve:
        n = min(ROUND, sess.left - reserve)
        pick = R10.local_round(sess, n, None, fitf)
        if not pick or not sess.run(pick, "코어 30 이어 찾기", cap=n):
            break
    best = R9.pack_vals(sess.book.best)
    sess.run(order_moves(sess, [q for _, q in best[1]], extra_top=R9.ORDER_TOP), "코어 30 순서", cap=sess.left)
    return {"start": start, "evals": sess.used}, sess.records


def cmd_corecheck(a: argparse.Namespace) -> int:
    """실험 22 같은 시즌(시즌 풀 · 시즌 보스 속성): 코어 없음 기록에서 고른 후보(core_candidates)를 코어 30으로 재평가(R) →
    그 위에서 코어 30 이어 찾기 CORE_EXTRA(RC). 같은 시즌 코어 30으로 따로 돌린 사전 계산(15,000평가, 시드 1개)의 최선과 비교한다.
    코어 30 기록에 같은 요청(배치 순서까지)이 있으면 그 값을 쓴다(같은 평가기 · options, 시뮬 0). 이어 찾기에 넣는 것은 R의 값뿐이다."""
    from nikke_opt.evaluator import make_evaluator
    R22 = sys.modules.get("run22") or _load("run22", EXP22 / "run22.py")
    LOG.mkdir(parents=True, exist_ok=True)
    with make_evaluator() as base:
        for s in [int(x) for x in a.season.split(",")]:
            out_f = LOG / f"corecheck_S{s:02d}.json"
            if out_f.exists():
                continue
            t0, sims0 = time.time(), base.sim_count
            no_recs = load_recs(EXP22 / "run_log" / f"precompute_S{s:02d}_nocore.jsonl.gz")
            co_recs = load_recs(EXP22 / "run_log" / f"precompute_S{s:02d}_core30.jsonl.gz")
            no, co = book_of(no_recs), book_of(co_recs)
            known = {tuple(r["squad"]): r["total_damage"] for r in co_recs if r.get("total_damage") is not None}
            ev = KnownEvaluator(base, known)
            nm = class_map(no)
            acct = R22.account(s, "core30")
            cands = core_candidates(no, [nm])
            sess = R9.Session(acct, ev, len(cands))
            sess.run(cands, "코어 30 재평가")
            r_recs = list(sess.records)
            r_sims = base.sim_count - sims0
            r_book = book_of(r_recs)
            r_map = class_map(r_book)
            cs, c_recs = continue_search(acct, ev, r_recs, CORE_EXTRA)
            rc_book = book_of(r_recs + c_recs)
            rc_map = class_map(rc_book)
            co_map = class_map(co)
            out = {"season": s, "candidates": len(cands), "reeval_sims": r_sims, "extra_evals": cs["evals"],
                   "sims": base.sim_count - sims0, "known_hits": ev.known_hits, "seconds": round(time.time() - t0, 1),
                   "nocore_map": nm, "core30_search": co_map, "reeval": r_map, "reeval_cont": rc_map,
                   "ratio_R": r_map["best"] / co_map["best"], "ratio_RC": rc_map["best"] / co_map["best"],
                   "n97": {"search": count_at(co_map, co_map["best"]), "R": count_at(r_map, co_map["best"]),
                           "RC": count_at(rc_map, co_map["best"])},
                   "evaluator": f"{base.version.get('repo')} {str(base.version.get('commit'))[:7]}"}
            with gzip.open(LOG / f"corecheck_S{s:02d}.jsonl.gz", "wt", encoding="utf-8") as f:
                for r in r_recs + c_recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            out_f.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()
                              if k not in ("nocore_map", "core30_search", "reeval", "reeval_cont")}, ensure_ascii=False), flush=True)
    return 0


def cmd_simcount(a: argparse.Namespace) -> int:
    """관리자 컨테이너 평가 캐시의 고유 평가 수를 보스 조건별로 센다 → run_log/sims_cache.json (관리자만, 캐시는 커밋 안 함).
    다시 돌린 부분은 part_*.json의 sims에 안 잡히므로(앞선 실행이 캐시에 남김) 이것이 실제 시뮬 수에 가깝다.
    포함: 시운전(작열 코어 없음 · 코어 30), corecheck(S40은 풍압 코어 30과 같은 요청, S34는 프로필이 있어 따로), 평가기 확인 7회.
    빠짐: 캐시 쓰기 경고(database is locked)로 안 남은 평가."""
    import sqlite3
    from collections import Counter
    db = ROOT / ".cache" / "evals.sqlite"
    con = sqlite3.connect(str(db), timeout=120)
    cnt: Counter = Counter()
    for (res,) in con.execute("select result from evals"):
        r = json.loads(res)
        b = r.get("boss") or {}
        prof = (r.get("spec") or {}).get("profile")
        cnt[f"{b.get('code')}|core{b.get('core_px') or 0}|{'profile' if prof is not None else 'default'}"] += 1
    out = {"by_condition": dict(sorted(cnt.items())), "total": sum(cnt.values()),
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "sims_cache.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- 분석

def verdict(rows: Sequence[Mapping[str, Any]]) -> str:
    """README §판단 기준(사전 등록)."""
    dm = [r["dM"] for r in rows]
    gb = [r["best_ratio"] for r in rows]
    best_ok = statistics.median(gb) >= 1 - 0.003 and min(gb) >= 1 - 0.010
    if statistics.median(dm) >= 1 and sum(1 for x in dm if x >= 0) >= 4 and best_ok:
        return "넓게 찾기가 지도를 넓힌다"
    if statistics.median(dm) >= 1 and not best_ok:
        return "지도는 넓지만 최선이 낮다"
    if statistics.median(dm) <= -1:
        return "기준선이 낫다"
    return "차이 없음"


def cmd_analyze(a: argparse.Namespace) -> int:
    rows, out = [], {"elements": {}}
    sc_f = LOG / "sims_cache.json"
    sc = json.loads(sc_f.read_text(encoding="utf-8"))["by_condition"] if sc_f.exists() else {}
    for el in ELEMENTS:
        summ = summary(el)
        if "W" not in summ:
            continue
        bm, wm = maps_of(el)
        ref = max(bm["best"], wm["best"])
        row = {"element": el, "B_best": bm["best"], "W_best": wm["best"], "best_ratio": wm["best"] / bm["best"],
               "MB": count_at(bm, ref), "MW": count_at(wm, ref), "MB95": count_at(bm, ref, LOW), "MW95": count_at(wm, ref, LOW),
               "sims": summ.get("sims_total"), "exact": bm["exact"] and wm["exact"],
               "sims_cache": sc.get(f"{el}|core0|default"), "sims_cache_core30": sc.get(f"{el}|core30|default")}
        row["dM"] = row["MW"] - row["MB"]
        core = None
        cf = edir(el) / "core30.jsonl.gz"
        if cf.exists():
            cb = book_of(load_recs(cf))
            cm = class_map(cb)
            core = {"best": cm["best"], "n97": count_at(cm, cm["best"]), "reps": cm["reps"],
                    "nocore_best_at_core": plan_total(cb, bm["reps"][0]["decks"]) / cm["best"]
                    if all(frozenset(q) in cb for q in bm["reps"][0]["decks"]) else None}
        rows.append(row)
        out["elements"][el] = {"row": row, "B": bm, "W": wm, "core30": core, "blocks": summ["W"]["blocks"]}
    if not rows:
        print("결과 없음")
        return 0
    out["verdict"] = verdict(rows) if len(rows) == len(ELEMENTS) else "미완(속성 일부)"
    dest = HERE if LOG == HERE / "run_log" else LOG          # 시운전(--log)은 그 폴더에 쓴다
    (dest / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    L = ["# 실험 30 결과 표", "", f"판단(사전 등록): **{out['verdict']}**", "",
         "| 속성 | B 최선(억) | W 최선 / B | M_B (≥97%) | M_W (≥97%) | ΔM | ≥95% B · W | 부분 합 시뮬 | 캐시 기준 시뮬(없음 · 코어 30) | 정확해 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['element']} | {r['B_best']:.1f} | {(r['best_ratio'] - 1) * 100:+.2f}% | {r['MB']} | {r['MW']} | {r['dM']:+d} | "
                 f"{r['MB95']} · {r['MW95']} | {r['sims']:,} | {r['sims_cache'] or 0:,} · {r['sims_cache_core30'] or 0:,} | "
                 f"{'O' if r['exact'] else 'X'} |")
    L += ["", "## 지도 대표(비율 = 그 기록 최선 대비, J 최대 = 다른 대표와의 J 중 최대)", ""]
    for el, e in out["elements"].items():
        for arm in ("B", "W"):
            m = e[arm]
            L.append(f"- {el} {arm}: " + " · ".join(f"{r['ratio'] * 100:.1f}%" + ("↓" if r.get("below") else "") for r in m["reps"]))
        if e["core30"]:
            c = e["core30"]
            L.append(f"- {el} 코어 30 재평가: 최선 {c['best']:.1f}억, ≥97% 대표 {c['n97']}, 대표 비율 "
                     + " · ".join(f"{r['ratio'] * 100:.1f}%" for r in c["reps"])
                     + (f", B 최선 5덱의 코어 30 값 = 재평가 최선의 {c['nocore_best_at_core'] * 100:.1f}%" if c["nocore_best_at_core"] else ""))
    (dest / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--element", required=True)
    r.add_argument("--seed-budget", type=int, default=SEED_BUDGET, help="시운전용(본 실행은 기본값)")
    r.add_argument("--w-budget", type=int, default=None,
                   help="시운전용. 주지 않으면 B 두 시드가 실제로 쓴 평가 수 − 앞부분(본 실행)")
    r.add_argument("--part", default="all", help="B_s0 · B_s1 · W · core30(쉼표로 여럿) · all")
    sub.add_parser("analyze")
    c = sub.add_parser("corecheck")
    c.add_argument("--season", required=True)
    sub.add_parser("simcount")
    p.add_argument("--log", type=Path, default=None, help="기록 폴더(시운전용, 기본 run_log)")
    a = p.parse_args(argv)
    if a.log is not None:
        global LOG
        LOG = a.log
    return {"run": cmd_run, "analyze": cmd_analyze, "corecheck": cmd_corecheck, "simcount": cmd_simcount}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
