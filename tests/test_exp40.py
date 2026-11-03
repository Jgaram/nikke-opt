"""실험 40(Deep Sets를 탐색 자료 크기로 재생) — 평가기 없이, 작은 가짜 자료로."""

import importlib.util
import random
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HAS_TORCH = importlib.util.find_spec("torch") is not None


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("an40", ROOT / "experiments" / "40_deepsets_search" / "an40.py")
G, M = A.G, A.M

NAMES = [f"n{i}" for i in range(12)]
AT = {n: {"weapon": G.WEAPONS[i % 6], "stage": G.STAGES[i % 3], "class": G.CLASSES[i % 3], "code": G.CODES[i % 5]}
      for i, n in enumerate(NAMES)}
EL = "작열"


def world(n=300, seed=0):
    """총딜 = 니케 기본값 합 × (n0 · n1이 함께면 2배)."""
    rng = random.Random(seed)
    base = {x: 1.0 + i for i, x in enumerate(NAMES)}
    comps = []
    while len(comps) < n:
        c = frozenset(rng.sample(NAMES, 5))
        if c not in comps:
            comps.append(c)
    vals = [sum(base[x] for x in c) * (2.0 if {"n0", "n1"} <= c else 1.0) * 1e9 for c in comps]
    return comps, vals


@unittest.skipUnless(HAS_TORCH, "torch 없음")
class FineTune(unittest.TestCase):
    def setUp(self):
        comps, vals = world(300)
        self.comps, self.vals = comps, vals
        cfg = G.DSConfig(d=4, hidden=32, max_epochs=40, patience=5, seeds=(1, 2), batch=64, lr=3e-3)
        tr = A.obs_of(comps[:200], vals[:200], EL)
        self.pre = G.DeepSets(NAMES, (EL, "수냉"), AT, cfg).fit(tr, valid=A.obs_of(comps[200:240], vals[200:240], EL))

    def test_finetune_keeps_norm_and_not_worse(self):
        tr = A.obs_of(self.comps[:200], self.vals[:200], EL)
        va = A.obs_of(self.comps[200:240], self.vals[200:240], EL)
        ft = A.finetune(self.pre, tr, va)
        self.assertEqual((ft.mu, ft.sd), (self.pre.mu, self.pre.sd))
        self.assertIsNot(ft.nets[0], self.pre.nets[0])          # 미리 학습 그물은 그대로
        te = self.comps[240:]
        a = np.log(self.vals[240:])
        e0 = np.mean((A.predict_each(self.pre, A.obs_of(te, None, EL)).mean(0) - a) ** 2)
        e1 = np.mean((A.predict_each(ft, A.obs_of(te, None, EL)).mean(0) - a) ** 2)
        self.assertLessEqual(e1, e0 * 1.5)

    def test_dsscore_units_and_spread(self):
        sc = A.DSScore(self.pre, EL)
        p, sd = sc.many(self.comps[240:])
        self.assertEqual(p.shape, (60,))
        self.assertTrue(np.all(sd >= 0))
        ratio = np.median(p / (np.array(self.vals[240:]) / A.E8))   # 억 단위로 실제와 비슷해야
        self.assertGreater(ratio, 0.5)
        self.assertLess(ratio, 2.0)
        self.assertGreater(M.spearman(self.vals[240:], list(p)), 0.5)


class Verdict(unittest.TestCase):
    def _rows(self, gap_d, rho_d):
        rows = {}
        for s in range(10):
            rows[s] = {"R0": {"gap": 0.15, "next_rho": 0.8},
                       "D1": {"gap": 0.15 + gap_d, "next_rho": 0.8 + rho_d},
                       "D2": {"gap": 0.15, "next_rho": 0.8}}
        return rows

    def test_lines(self):
        self.assertEqual(A.verdict(self._rows(-0.06, 0.0))["D1"]["line"], 1)
        self.assertEqual(A.verdict(self._rows(-0.06, 0.0))["stage2"], "D1")
        self.assertEqual(A.verdict(self._rows(0.0, 0.06))["D1"]["line"], 2)
        self.assertEqual(A.verdict(self._rows(-0.06, -0.05))["D1"]["line"], 3)
        self.assertEqual(A.verdict(self._rows(0.0, 0.0))["D1"]["line"], 4)
        self.assertIsNone(A.verdict(self._rows(0.0, 0.0))["stage2"])

    def test_tie_prefers_d1(self):
        rows = self._rows(-0.06, 0.0)
        for r in rows.values():
            r["D2"] = {"gap": 0.15 - 0.065, "next_rho": 0.8}
        self.assertEqual(A.verdict(rows)["stage2"], "D1")
        for r in rows.values():
            r["D2"] = {"gap": 0.15 - 0.09, "next_rho": 0.8}
        self.assertEqual(A.verdict(rows)["stage2"], "D2")


class TwoPass(unittest.TestCase):
    """판 d의 두 번 돌기(기록 → 한꺼번에 예측 → 다시 돌기)가 같은 점수로 base `local_round`와 똑같이 고른다."""

    @classmethod
    def setUpClass(cls):
        cls.R = _load("run40", ROOT / "experiments" / "40_deepsets_search" / "run40.py")

    def _sess(self, seed=0):
        from types import SimpleNamespace
        R = self.R
        rng = random.Random(seed)
        names = [f"m{i}" for i in range(24)]
        owned = {n: {"burst": "123"[i % 3]} for i, n in enumerate(names)}
        book = SimpleNamespace(best={})
        while len(book.best) < 80:
            sq = tuple(sorted(rng.sample(names, 5)))
            book.best[frozenset(sq)] = (rng.uniform(10, 50), sq)
        acct = SimpleNamespace(owned=owned, names=names)
        return SimpleNamespace(acct=acct, book=book, fresh=lambda sq: True, pack=lambda: R.R9.pack_vals(book.best))

    def _check(self, lineage):
        R = self.R
        sess = self._sess()
        ridge = R.R10.DualFit(sess.book, sess.acct.names)

        class Same:
            def __init__(s):
                s.calls = 0
            def refresh(s, book):
                pass
            def prefill(s, comps):
                s.calls += 1
            def __call__(s, c):
                return ridge(c)

        lin_a = None if lineage is None else set(lineage)
        lin_b = None if lineage is None else set(lineage)
        want = R.BASE_ROUND(sess, 100, lin_a, lambda book, names: ridge)
        st = Same()
        got = R.make_round(st)(sess, 100, lin_b, None)
        self.assertEqual(want, got)
        self.assertEqual(lin_a, lin_b)          # 기록용 첫 번째 돌기가 계보를 건드리지 않는다
        self.assertEqual(st.calls, 1)

    def test_same_pick_no_lineage(self):
        self._check(None)

    def test_same_pick_lineage(self):
        sess = self._sess()
        top = sorted(sess.book.best.values(), reverse=True)[:30]
        self._check({frozenset(q) for _, q in top})


@unittest.skipUnless(HAS_TORCH, "torch 없음")
class D2StateTest(unittest.TestCase):
    def test_refit_schedule_and_cache(self):
        R = _load("run40", ROOT / "experiments" / "40_deepsets_search" / "run40.py")
        comps, vals = world(300)
        cfg = G.DSConfig(d=4, hidden=16, max_epochs=10, patience=3, seeds=(1,), batch=64, lr=3e-3)
        pre = G.DeepSets(NAMES, (EL, "수냉"), AT, cfg).fit(A.obs_of(comps[:200], vals[:200], EL))
        st = R.D2State(pre, EL, "t")
        book = {c: (v / A.E8, tuple(sorted(c))) for c, v in zip(comps[:100], vals[:100])}
        st.refresh(book)
        st.refresh(book)
        self.assertEqual(st.refits, 1)
        st.prefill(comps[200:250])
        self.assertEqual(st.predicted, 50)
        x = st(comps[200])
        self.assertEqual(st.predicted, 50)       # 캐시에서
        self.assertGreater(x, 0)
        book.update({c: (v / A.E8, tuple(sorted(c))) for c, v in zip(comps[100:100 + R.REFIT], vals[100:100 + R.REFIT])})
        if len(book) - st.n_fit >= R.REFIT:
            st.refresh(book)
            self.assertEqual(st.refits, 2)
            self.assertEqual(st.cache, {})


if __name__ == "__main__":
    unittest.main()
