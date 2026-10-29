"""사전 실험 4 — 개선 여지. 랭커 구성 기준선보다 나은 5덱을 시뮬로 찾을 수 있나?

실험 2의 결과(무작위 + 랭커 구성 + 순서 전수)에서 출발해, 작은 예산으로 다음을 반복한다.
이 레포가 만들 시스템의 축소판이다 — 결과는 「얼마나 나아질 여지가 있나」의 하한이다.

1. 이웃 생성 — 지금까지 평가한 상위 구성마다 한 명 교체(같은 버스트 단계끼리, 틀 유지).
   교체된 자리에 새 니케를 그대로 넣으므로 배치 순서는 부모를 따른다.
2. 대리 모델 — 지금까지의 모든 180초 결과로 「니케 + 짝」 릿지 회귀를 학습해 이웃 점수를 추정,
   추정 상위만 시뮬로 돌린다.
3. 덱 단위 개선 — 지금 최선 5덱의 각 덱에서 한 명을 *다른 네 덱이 안 쓰는* 니케로 바꾸거나,
   두 덱이 같은 단계 니케를 맞바꾼다. 대리 모델의 「예상 이득」 순으로 고른다.
   (1의 이웃은 상위 구성 근처에 몰려 1덱만 강해지고 다른 덱과 겹친다 — 1차 실행에서 확인)
4. 순서 다듬기 — 마지막에 상위 구성과 최선 5덱의 「딜이 달라질 수 있는」 배치 순서를 전부 돌린다.
5. 조립 — 겹치지 않는 5개를 정확히 고른다(분기 한정). 랭커 구성만으로 고른 묶음, 실제 랭커 1위의 5덱과 비교.

「평가 수」는 이번 실행이 새로 요청한 스쿼드 수다(캐시에 있던 것도 센다 — 다시 돌려도 같은 값).

사용: NIKKE_SIM_BIN=... (또는 NIKKE_CALC_DIR=...) python search.py [--rounds 3 --per-round 150 --pack-rounds 3 --pack-per-round 100]
      → log.jsonl(이번에 돌린 것), summary.json, 표준출력 마크다운
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXP2 = HERE.parent / "02_score_distribution"
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(EXP2))
from nikke_opt.evaluator import EvalRequest, make_evaluator  # noqa: E402
from run import BOSS, distinct_orders  # noqa: E402

E8 = 1e8
PARENTS = 40       # 이웃을 만들 상위 구성 수
PER_PARENT = 8     # 한 부모에서 한 라운드에 고르는 이웃 상한 (다양성)
LAM_U, LAM_P = 1.0, 10.0


class Book:
    """평가한 스쿼드 기록. 구성(frozenset) → 그 구성의 최선 (딜, 순서)."""

    def __init__(self):
        self.seen: dict[tuple, float] = {}
        self.best: dict[frozenset, tuple[float, tuple]] = {}

    def add(self, squad: tuple, dmg: float) -> None:
        self.seen[squad] = dmg
        c = frozenset(squad)
        if c not in self.best or dmg > self.best[c][0]:
            self.best[c] = (dmg, squad)


def fit(book: Book, names: list[str]):
    ni = {n: i for i, n in enumerate(names)}
    comps = list(book.best)
    pairs = sorted({p for c in comps for p in combinations(sorted(c), 2)})
    pi = {p: i for i, p in enumerate(pairs)}

    def x(c):
        v = np.zeros(1 + len(names) + len(pairs))
        v[0] = 1
        for n in c:
            v[1 + ni[n]] = 1
        for p in combinations(sorted(c), 2):
            if p in pi:
                v[1 + len(names) + pi[p]] = 1
        return v

    X = np.array([x(c) for c in comps])
    y = np.array([book.best[c][0] for c in comps])
    pen = np.r_[0.0, np.full(len(names), LAM_U), np.full(len(pairs), LAM_P)]
    w = np.linalg.solve(X.T @ X + np.diag(pen), X.T @ y)
    return lambda c: float(x(c) @ w)


def neighbors(squad: tuple, pool: dict) -> list[tuple]:
    out = []
    for i, n in enumerate(squad):
        stage = pool[n]["burst"]
        for m in pool:
            if m not in squad and pool[m]["burst"] == stage:
                out.append(squad[:i] + (m,) + squad[i + 1:])
    return out


def pack_moves(decks: list[tuple], pool: dict, score) -> list[tuple[float, list[tuple]]]:
    """최선 5덱을 고치는 수: (예상 이득, 새로 돌릴 스쿼드들). 이득 = 모델 예측 차이."""
    used = {n for d in decks for n in d}
    pred = {d: score(frozenset(d)) for d in decks}
    moves = []
    for d in decks:
        for i, n in enumerate(d):
            for m in pool:
                if m not in used and pool[m]["burst"] == pool[n]["burst"]:
                    nd = d[:i] + (m,) + d[i + 1:]
                    moves.append((score(frozenset(nd)) - pred[d], [nd]))
    for a, b in combinations(decks, 2):
        for i, n in enumerate(a):
            for j, m in enumerate(b):
                if pool[n]["burst"] == pool[m]["burst"]:
                    na, nb = a[:i] + (m,) + a[i + 1:], b[:j] + (n,) + b[j + 1:]
                    gain = score(frozenset(na)) + score(frozenset(nb)) - pred[a] - pred[b]
                    moves.append((gain, [na, nb]))
    return sorted(moves, key=lambda mv: -mv[0])


def pack(book: Book, k: int = 5, only=None):
    """겹치지 않는 k개 구성의 딜 합 최대 — 점수 내림차순 분기 한정 (정확해)."""
    cands = sorted(((d, sq) for c, (d, sq) in book.best.items() if only is None or c in only), reverse=True)
    best = [0.0, []]

    def dfs(start, used, chosen, total):
        if len(chosen) == k:
            if total > best[0]:
                best[:] = [total, list(chosen)]
            return
        for i in range(start, len(cands)):
            d, sq = cands[i]
            if total + d * (k - len(chosen)) <= best[0]:
                return
            if used.isdisjoint(sq):
                chosen.append((d, sq))
                dfs(i + 1, used | set(sq), chosen, total + d)
                chosen.pop()

    dfs(0, frozenset(), [], 0.0)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--per-round", type=int, default=150)
    ap.add_argument("--pack-rounds", type=int, default=3)
    ap.add_argument("--pack-per-round", type=int, default=100)
    ap.add_argument("--order-top", type=int, default=20, help="순서를 전수로 다듬을 상위 구성 수")
    ap.add_argument("--jobs", type=int)
    args = ap.parse_args()

    pool = json.loads((EXP2 / "pool.json").read_text(encoding="utf-8"))["pool"]
    burst = {k: v["burst"] for k, v in pool.items()}
    rk = json.loads((EXP2 / "ranker_squads.json").read_text(encoding="utf-8"))
    names = sorted(pool)
    book = Book()
    for s in (EXP2 / "results.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(s)
        if r["error"] is None:
            book.add(tuple(r["squad"]), r["total_damage"] / E8)
    start_n = len(book.seen)
    ranker_comps = {frozenset(s["squad"]) for s in rk["squads"]}

    ev = make_evaluator(jobs=args.jobs)
    log = open(HERE / "log.jsonl", "w", encoding="utf-8")

    evals = [0]

    def run(squads: list[tuple], phase: str) -> None:
        evals[0] += len(squads)
        for i in range(0, len(squads), 40):
            part = squads[i:i + 40]
            for sq, r in zip(part, ev.evaluate([EvalRequest(sq, boss=BOSS) for sq in part])):
                if r.error is None:
                    book.add(sq, r.total_damage / E8)
                log.write(json.dumps({"phase": phase, "squad": list(sq), "total_damage": r.total_damage,
                                      "error": r.error}, ensure_ascii=False) + "\n")
            log.flush()
            print(f"  {phase}: {min(i + 40, len(squads))}/{len(squads)} · 평가 누적 {evals[0]}"
                  f" · 시뮬 {ev.sim_count}",
                  file=sys.stderr, flush=True)

    history = [{"단계": "출발 (실험 2 결과)", "평가": 0, "최선 5덱": pack(book)[0],
                "최선 구성": max(d for d, _ in book.best.values())}]
    for rnd in range(1, args.rounds + 1):
        score = fit(book, names)
        parents = sorted(book.best.values(), reverse=True)[:PARENTS]
        per_parent: dict[tuple, list] = defaultdict(list)
        for _, sq in parents:
            for nb in neighbors(sq, pool):
                if frozenset(nb) not in book.best:
                    per_parent[sq].append((score(frozenset(nb)), nb))
        cands, seen = [], set()
        for sq, lst in per_parent.items():
            for s, nb in sorted(lst, reverse=True)[:PER_PARENT]:
                if frozenset(nb) not in seen:
                    seen.add(frozenset(nb))
                    cands.append((s, nb))
        pick = [nb for _, nb in sorted(cands, reverse=True)[:args.per_round]]
        run(pick, f"이웃 {rnd}")
        history.append({"단계": f"이웃 라운드 {rnd}", "평가": evals[0], "최선 5덱": pack(book)[0],
                        "최선 구성": max(d for d, _ in book.best.values())})

    for rnd in range(1, args.pack_rounds + 1):
        score = fit(book, names)
        decks = [sq for _, sq in pack(book)[1]]
        pick, seen = [], set(book.seen)
        for gain, new in pack_moves(decks, pool, score):
            if len(pick) + len(new) > args.pack_per_round:
                break
            new = [nd for nd in new if nd not in seen and frozenset(nd) not in book.best]
            if not new:
                continue
            pick += new
            seen.update(new)
        run(pick, f"덱 개선 {rnd}")
        history.append({"단계": f"덱 개선 라운드 {rnd}", "평가": evals[0], "최선 5덱": pack(book)[0],
                        "최선 구성": max(d for d, _ in book.best.values())})

    tops = sorted(book.best.values(), reverse=True)[:args.order_top]
    # 최선 5덱에 든 구성도 순서를 다듬는다
    tops += [(d, sq) for d, sq in pack(book)[1] if (d, sq) not in tops]
    orders = [p for _, sq in tops for p in distinct_orders(sq, burst) if p not in book.seen]
    run(orders, "순서")
    history.append({"단계": "순서 다듬기", "평가": evals[0], "최선 5덱": pack(book)[0],
                    "최선 구성": max(d for d, _ in book.best.values())})
    log.close()

    # 비교 기준
    rk_sq = [tuple(s["squad"]) for s in rk["squads"]]
    players = [sum(book.seen[rk_sq[i]] for i in p["squads"]) for p in rk["players"]]
    best_player = int(np.argmax(players))
    rk_pack = pack(book, only=ranker_comps)
    final = pack(book)

    def fmt(sq):
        return " → ".join(sq)

    print(f"# 실험 4 결과 — 출발 {start_n}개(실험 2) + 이번 평가 {evals[0]}회\n")
    print("| 단계 | 이번 평가 누적 | 최선 5덱 합(억) | 최선 단일 구성(억) |\n|---|---|---|---|")
    for h in history:
        print(f"| {h['단계']} | {h['평가']} | {h['최선 5덱']:.1f} | {h['최선 구성']:.1f} |")
    print("\n| 묶음 | 5덱 합(억) | 랭커 1위 대비 |\n|---|---|---|")
    for name, v in [("실제 랭커 5덱 중 최고 (같은 육성·S40 시뮬)", players[best_player]),
                    ("랭커 구성만으로 겹치지 않게 다시 고른 최선 (순서 다듬기 포함)", rk_pack[0]),
                    ("탐색 후 최선", final[0])]:
        print(f"| {name} | {v:.1f} | {v / players[best_player] - 1:+.1%} |")
    print("\n최선 5덱:\n")
    for d, sq in final[1]:
        tag = "랭커 구성" if frozenset(sq) in ranker_comps else "새 구성"
        print(f"- {d:.1f}억 ({tag}) — {fmt(sq)}")
    print("\n랭커 1위의 5덱:\n")
    for i in rk["players"][best_player]["squads"]:
        print(f"- {book.seen[rk_sq[i]]:.1f}억 — {fmt(rk_sq[i])}")

    summary = {"boss": BOSS, "evaluator": ev.version, "start_evals": start_n, "evals": evals[0],
               "sims_this_run": ev.sim_count,
               "history": history, "ranker_best_player": players[best_player],
               "ranker_comps_pack": {"total": rk_pack[0], "squads": [list(s) for _, s in rk_pack[1]]},
               "final": {"total": final[0], "squads": [[d, list(s)] for d, s in final[1]]}}
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
