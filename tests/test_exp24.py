"""실험 24 — 비용 상한 묶기(`run9.pack_vals(cost, budget, deadline)`) · 해석 기준(시뮬 없음)."""

import importlib.util
import random
import sys
import time
import unittest
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "24_diverse_pick"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = sys.modules.get("pick24") or _load("pick24", EXP / "pick24.py")
R9 = P.R9


def instance(seed, n_names=12, n_cands=30, size=3):
    rng = random.Random(seed)
    vals, cost = {}, {}
    while len(vals) < n_cands:
        c = frozenset(rng.sample(range(n_names), size))
        vals[c] = (round(rng.uniform(1, 10), 3), tuple(sorted(c)))
        cost[c] = rng.randint(0, 4)
    return vals, cost


def brute(vals, cost, k, budget):
    best = 0.0
    for combo in combinations(vals, k):
        if len(frozenset().union(*combo)) < k * len(next(iter(combo))):
            continue
        if sum(cost[c] for c in combo) > budget:
            continue
        best = max(best, sum(vals[c][0] for c in combo))
    return best


class TestCostPack(unittest.TestCase):
    def test_matches_brute_force(self):
        for seed in range(12):
            vals, cost = instance(seed)
            for budget in (0, 2, 4, 7, 20):
                t, d = R9.pack_vals(vals, k=3, cost=cost, budget=budget)
                want = brute(vals, cost, 3, budget)
                self.assertAlmostEqual(t, want, places=9, msg=(seed, budget))
                if d:
                    self.assertLessEqual(sum(cost[frozenset(q)] for _, q in d), budget)
                    self.assertEqual(len(frozenset().union(*(frozenset(q) for _, q in d))), 9)

    def test_no_cost_same_as_before(self):
        for seed in range(5):
            vals, cost = instance(seed)
            self.assertEqual(R9.pack_vals(vals, k=3), R9.pack_vals(vals, k=3, cost={c: 0 for c in vals}, budget=0))

    def test_deadline_returns_feasible_incumbent(self):
        vals, cost = instance(3, n_names=40, n_cands=400, size=5)
        try:
            t, d = R9.pack_vals(vals, k=5, cost=cost, budget=6, deadline=time.monotonic() - 1)
        except R9.PackTimeout as e:
            t, d = e.total, e.decks
        if d:
            self.assertLessEqual(sum(cost[frozenset(q)] for _, q in d), 6)
            self.assertAlmostEqual(t, sum(v for v, _ in d))

    def test_multiplier_bound_is_upper(self):
        for seed in range(6):
            vals, cost = instance(seed, n_names=15, n_cands=40, size=3)
            book = vals
            orig = R9.pack_vals
            R9.pack_vals = lambda v, k=3, **kw: orig(v, k=3, **kw)     # 시험 문제는 3덱
            try:
                for budget in (1, 3, 6):
                    up, feas = P.multiplier_bound(book, cost, budget)
                    want = brute(vals, cost, 3, budget)
                    self.assertGreaterEqual(up + 1e-9, want)
                    if feas:
                        self.assertLessEqual(feas[0], want + 1e-9)
            finally:
                R9.pack_vals = orig


class TestPick24(unittest.TestCase):
    def test_budget_of(self):
        self.assertEqual([P.budget_of(t) for t in (0.5, 0.4, 0.3, 0.2, 0.1, 0.0)], [33, 28, 23, 16, 9, 0])
        for t in (0.5, 0.4, 0.3, 0.2, 0.1):
            s = P.budget_of(t)
            self.assertLessEqual(s / (100 - s), t + 1e-12)
            self.assertGreater((s + 1) / (100 - s - 1), t)

    def test_pair_cost(self):
        best = [frozenset("abcde"), frozenset("fghij")]
        cost = P.pair_cost({frozenset("abfgz"): 1, frozenset("abcxy"): 1}, best)
        self.assertEqual(cost, {frozenset("abfgz"): 2, frozenset("abcxy"): 3})

    def test_verdict(self):
        self.assertEqual(P.verdict_of([0.98, 0.975, 0.99, 0.96]), "고르기로 충분")
        self.assertEqual(P.verdict_of([0.98, 0.96, 0.96, 0.99]), "일부")
        self.assertEqual(P.verdict_of([0.90, 0.94, 0.99]), "탐색 보강 필요")
        self.assertEqual(P.verdict_of([0.99, None]), "탐색 보강 필요")


if __name__ == "__main__":
    unittest.main()
