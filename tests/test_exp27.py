"""실험 27(대안 근처 탐색 + 후처리, w1~w8) — 평가기 없이."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP27 = ROOT / "experiments" / "27_alt_local_check"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R27 = sys.modules.get("run27") or _load("run27", EXP27 / "run27.py")


def _book():
    g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJ"]
    book = {frozenset(d): (20.0 - i, d) for i, d in enumerate(g)}
    mix = [tuple(g[r][(c + r) % 5] for r in range(5)) for c in range(5)]
    for i, d in enumerate(mix):
        book[frozenset(d)] = (15.0 - 0.1 * i, d)
    return g, book


class TestRun27(unittest.TestCase):
    def test_settings_match_exp25_26(self):
        self.assertEqual((R27.THETA, R27.EXTRA, R27.ROUND, R27.RESERVE), (0.2, 1000, 100, 125))
        self.assertEqual((R27.ALT_RATIO, R27.PASS_COUNT), (R27.R25.ALT_RATIO, R27.R25.PASS_COUNT))

    def test_jpick_fixed_respects_reference_and_warm_start(self):
        g, book = _book()
        ref = [list(d) for d in g[:5]]
        cold = R27.jpick_fixed(book, ref, {})
        self.assertEqual(len(cold["decks"]), 5)
        self.assertLessEqual(R27.SIM.pair_jaccard(ref, cold["decks"]), 0.2 + 1e-12)
        warm = R27.jpick_fixed(book, ref, {}, prev=cold)
        self.assertEqual({frozenset(q) for q in cold["decks"]}, {frozenset(q) for q in warm["decks"]})
        self.assertAlmostEqual(cold["total"], warm["total"])
        boosted = R27.jpick_fixed(book, ref, {g[5]: 100.0})     # 운용 값이 기본보다 크면 그 값으로 고른다
        self.assertGreater(boosted["total"], cold["total"])

    def test_verdict(self):
        self.assertTrue(R27.verdict([0.98] * 6 + [0.9] * 2).startswith("통과"))
        self.assertTrue(R27.verdict([0.98] * 5 + [0.9] * 3).startswith("미통과"))


if __name__ == "__main__":
    unittest.main()
