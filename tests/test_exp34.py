"""실험 34(대리 모델 넓게 비교) — 평가기 없이, 작은 가짜 자료로."""

import importlib.util
import random
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HAS = {m: importlib.util.find_spec(m) is not None for m in ("lightgbm", "sklearn", "torch", "scipy")}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = sys.modules.get("models34") or _load("models34", ROOT / "experiments" / "34_surrogate_compare" / "models34.py")
M = sys.modules.get("roles33") or _load("roles33", ROOT / "experiments" / "33_role_vectors" / "roles33.py")

NAMES = [f"n{i}" for i in range(12)]
AT = {n: {"weapon": G.WEAPONS[i % 6], "stage": G.STAGES[i % 3], "class": G.CLASSES[i % 3], "code": G.CODES[i % 5]}
      for i, n in enumerate(NAMES)}
ELS = ("작열", "수냉")


def world(n=300, seed=0):
    """총딜 = 니케 기본값 합 × (n0 · n1이 함께면 2배). 속성 두 개."""
    rng = random.Random(seed)
    base = {x: 1.0 + i for i, x in enumerate(NAMES)}
    obs, seen = [], set()
    while len(obs) < n:
        sq = tuple(rng.sample(NAMES, 5))
        el = rng.choice(ELS)
        key = (frozenset(sq), el)
        if key in seen:
            continue
        seen.add(key)
        t = sum(base[x] for x in sq) * (2.0 if "n0" in sq and "n1" in sq else 1.0) * 1e9
        obs.append(M.Obs(frozenset(sq), el, sq, t, tuple(t / 5 for _ in sq)))
    return obs


class Features(unittest.TestCase):
    def test_table_shape_and_counts(self):
        obs = world(20)
        X = G.table(obs, NAMES, ELS, AT)
        self.assertEqual(X.shape, (20, len(NAMES) + len(ELS) + G.N_MEMBER))
        self.assertTrue(np.all(X[:, :len(NAMES)].sum(1) == 5))
        self.assertTrue(np.all(X[:, len(NAMES):len(NAMES) + len(ELS)].sum(1) == 1))
        # 무기 · 단계 · 클래스 · 코드 개수는 각각 5명
        off = len(NAMES) + len(ELS)
        for a, b in ((0, 6), (6, 10), (10, 13), (13, 18)):
            self.assertTrue(np.all(X[:, off + a:off + b].sum(1) == 5))

    def test_adv_flag(self):
        # 작열 코드는 풍압 보스에 우코
        x = next(n for n in NAMES if AT[n]["code"] == "작열")
        self.assertEqual(G.member_attr(x, "풍압", AT)[-1], 1.0)
        self.assertEqual(G.member_attr(x, "수냉", AT)[-1], 0.0)

    def test_set_kernel(self):
        self.assertAlmostEqual(float(G.set_kernel(5)), 1.0)
        self.assertAlmostEqual(float(G.set_kernel(0)), 0.0)
        k = G.set_kernel(np.arange(6))
        self.assertTrue(np.all(np.diff(k) > 0))


class Models(unittest.TestCase):
    def _check(self, mdl, fit_kw=None):
        obs = world(300)
        tr, te = obs[:240], obs[240:]
        mdl.fit(tr, **(fit_kw or {}))
        p = mdl.predict_total(te)
        self.assertEqual(p.shape, (len(te),))
        self.assertTrue(np.all(p > 0))
        rho = M.spearman([o.total for o in te], p)
        self.assertGreater(rho, 0.5)
        return mdl

    @unittest.skipUnless(HAS["scipy"], "scipy 없음")
    def test_gp(self):
        mdl = self._check(G.JaccardGP(NAMES, ELS, AT, G.GPConfig(w_attr=0.2, noise=0.1, chunk=50)))
        mu, sd = mdl.predict(world(300)[240:], var=True)
        self.assertTrue(np.all(sd > 0))

    @unittest.skipUnless(HAS["lightgbm"], "lightgbm 없음")
    def test_gbm(self):
        obs = world(300)
        m = G.GBM(NAMES, ELS, AT, G.GBMConfig(num_leaves=7, min_data_in_leaf=5, max_rounds=300, early_stop=20))
        m.fit(obs[:200], valid=obs[200:240])
        self.assertIsNotNone(m.best_iter)
        self._check(G.GBM(NAMES, ELS, AT, G.GBMConfig(num_leaves=7, min_data_in_leaf=5, rounds=m.best_iter)))

    @unittest.skipUnless(HAS["sklearn"], "scikit-learn 없음")
    def test_rf(self):
        self._check(G.RF(NAMES, ELS, AT, G.RFConfig(n_estimators=30)))

    @unittest.skipUnless(HAS["torch"], "torch 없음")
    def test_deepsets(self):
        obs = world(300)
        cfg = G.DSConfig(d=4, hidden=32, max_epochs=40, patience=5, seeds=(1, 2), batch=64, lr=3e-3)
        m = G.DeepSets(NAMES, ELS, AT, cfg).fit(obs[:200], valid=obs[200:240])
        self.assertIsNotNone(m.best_epoch)
        cfg.epochs = m.best_epoch
        self._check(G.DeepSets(NAMES, ELS, AT, cfg))

    def test_order_free(self):
        """배치 순서만 다른 관측은 표 특징이 같다."""
        o = world(1)[0]
        o2 = M.Obs(o.comp, o.element, tuple(reversed(o.squad)), o.total, o.members)
        self.assertTrue(np.array_equal(G.table([o], NAMES, ELS, AT), G.table([o2], NAMES, ELS, AT)))


class Boot(unittest.TestCase):
    def test_bootstrap_sign(self):
        obs = world(300)
        act = np.array([o.total for o in obs])
        good = act + np.random.default_rng(0).normal(0, 1e8, len(act))
        bad = act + np.random.default_rng(1).normal(0, 1e10, len(act))
        b = G.bootstrap_delta(obs, good, bad, M.top_metrics, ELS, B=200)
        self.assertGreater(b["p5"], 0)
        self.assertLessEqual(b["p5"], b["p50"])
        self.assertLessEqual(b["p50"], b["p95"])


if __name__ == "__main__":
    unittest.main()
