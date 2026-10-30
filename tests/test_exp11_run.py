"""실험 11 실행기(run11.py) — 가짜 평가기로 확인한다."""

import os
import random
import sys
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP11 = ROOT / "experiments" / "11_wide_precompute"
if str(EXP11) not in sys.path:
    sys.path.insert(0, str(EXP11))

import run11 as T  # noqa: E402
from tests.test_exp10_run import FakeEv  # noqa: E402

R10, S4 = T.R10, T.S4


def random_book(n, seed=3, names=None):
    names = list(names or T.P177)
    rng = random.Random(seed)
    w = {x: rng.uniform(1, 10) for x in names}
    b = S4.Book()
    while len(b.best) < n:
        sq = tuple(rng.sample(names[:120] if rng.random() < 0.7 else names, 5))
        v = sum(w[x] for x in sq) + sum(2.0 for a in sq for c in sq if a < c and (len(a) + len(c)) % 5 == 0)
        b.add(sq, v + rng.gauss(0, 1))
    return b


class TestCGFit(unittest.TestCase):
    def test_same_as_dual(self):
        names = list(T.P177)
        b = random_book(800)
        d, c = R10.DualFit(b, names), T.CGFit(b, names)
        rng = random.Random(5)
        tests = [frozenset(rng.sample(names, 5)) for _ in range(100)] + list(b.best)[:100] + [frozenset()]
        for x in tests:
            self.assertAlmostEqual(d(x), c(x), places=5)
        cur = list(tests[0])[:3]
        opts = [n for n in names if n not in cur][:40]
        for a, e in zip(d.add_scores(cur, opts), c.add_scores(cur, opts)):
            self.assertAlmostEqual(a, e, places=5)
        self.assertEqual(len(c.add_scores([], opts)), len(opts))

    def test_warm_start_same_answer(self):
        names = list(T.P177)
        b = random_book(600, seed=9)
        T.CGFit(b, names)
        self.assertTrue(hasattr(b, "_cg_warm"))
        b2 = random_book(600, seed=9)
        x = frozenset(list(b.best)[0])
        for _ in range(30):  # 표본을 늘린 뒤 다시 풀어도 처음부터 푼 것과 같다
            sq = tuple(random.Random(len(b.best)).sample(names, 5))
            b.add(sq, 40.0)
            b2.add(sq, 40.0)
        self.assertAlmostEqual(T.CGFit(b, names)(x), T.CGFit(b2, names)(x), places=6)

    def test_switch(self):
        small = random_book(50)
        self.assertIsInstance(T.fit_big(small, T.P177), R10.DualFit)
        old = T.DUAL_MAX
        try:
            T.DUAL_MAX = 10
            self.assertIsInstance(T.fit_big(small, T.P177), T.CGFit)
        finally:
            T.DUAL_MAX = old
        self.assertIs(R10.fit_for(60), S4.fit)
        self.assertIs(R10.fit_for(177), T.fit_big)


class TestNarrow(unittest.TestCase):
    def test_rule(self):
        b = random_book(400, seed=4)
        nm = T.narrow(b.best)
        self.assertEqual(len(nm), T.NARROW_M)
        self.assertEqual(nm, sorted(set(nm)))
        cnt = Counter(T.BURST[n] for n in nm)
        for s, q in T.NARROW_MIN.items():
            self.assertGreaterEqual(cnt[s], q)
        self.assertEqual(nm, T.narrow(dict(reversed(list(b.best.items())))))  # 입력 순서와 무관
        top = max(b.best.values())[1]
        self.assertTrue(set(top) <= set(nm))  # 최고 구성의 니케는 모두 남는다

    def test_minimum_forces_stage(self):
        names = list(T.P177)
        ones = [n for n in names if T.BURST[n] == "1"]
        rest = [n for n in names if T.BURST[n] != "1"]
        best = {frozenset(rest[i:i + 5]): (100.0 - i, tuple(rest[i:i + 5])) for i in range(0, 130, 5)}
        best.update({frozenset(ones[i:i + 5]): (1.0, tuple(ones[i:i + 5])) for i in range(0, 30, 5)})
        nm = T.narrow(best)
        self.assertEqual(sum(T.BURST[n] == "1" for n in nm), 10)

    def test_combined_coef(self):
        inner = {"a": 0.5, "b": -0.2}
        outer = {"a": 9.0, "b": 9.0, "c": 3.0, "d": 1.0}
        c = T.combined_coef(inner, outer)
        self.assertEqual(c["a"], 0.5)
        self.assertLess(c["c"], min(inner.values()))
        self.assertGreater(c["c"], c["d"])

    def test_stage1_record(self):
        st, best = T.stage1()
        self.assertEqual(st["evals"], 4454)
        self.assertEqual(len(st["coef"]), 177)
        self.assertGreater(len(best), 4000)
        self.assertEqual(len(T.narrow(best)), 60)


class TestRuns(unittest.TestCase):
    def test_roster_account_run(self):
        ev = FakeEv()
        names = T.narrow(random_book(300, seed=2).best)
        acct = T.RosterAccount("pre-N60", names, pool=60)
        self.assertEqual(acct.names, sorted(names))
        self.assertTrue(all(set(v) == {"burst"} for v in acct.owned.values()))
        summ, recs, sess = R10.run_method(acct, "G+E", 600, ev, pool=60)
        self.assertLessEqual(summ["evals"], 600)
        self.assertTrue(all(n in names for r in recs for n in r["squad"]))
        ext = T.extract(sess, acct, S4.fit)
        self.assertTrue(1 <= len(ext["sets"]) <= T.PRE_SETS)
        self.assertEqual(set(ext["coef"]), set(names))

    def test_account_methods(self):
        ev = FakeEv()
        sc = R10.scenarios("val")[0]
        acct = T.pre_account177()
        _, _, sess = R10.run_method(acct, "G+E", 400, ev, pool=177)
        pre = T.extract(sess, acct, T.fit_big)
        summ, _ = T.run_account(sc, "PB15", 300, ev, pre)
        self.assertEqual(summ["method"], "PB15")
        self.assertEqual(summ["pool"], 177)
        same, _ = T.run_account(sc, "P", 300, ev, pre)  # 같은 사전 계산이면 기호만 다르다
        self.assertEqual(same["final"]["total"], summ["final"]["total"])
        k, _ = T.run_account(sc, "K", 300, ev, None)
        self.assertEqual(k["method"], "K")


if __name__ == "__main__":
    unittest.main()
