"""실험 28(큰 분류 · 세부 분류, 시뮬 0) — 평가기 없이."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


T = sys.modules.get("tree28") or _load("tree28", ROOT / "experiments" / "28_plan_tree" / "tree28.py")


def _vals():
    g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJ"]
    vals = {frozenset(d): (20.0 - i, d) for i, d in enumerate(g)}
    for s in range(1, 5):                                   # 섞인 덱들
        for c in range(5):
            d = tuple(g[(r + s * c) % 10][(c + r) % 5] for r in range(5))
            if len(set(x[0] for x in d)) == 5:
                vals.setdefault(frozenset(d), (14.0 - 0.1 * c - s, d))
    return g, vals


class TestTree28(unittest.TestCase):
    def test_pick_far_respects_every_reference(self):
        g, vals = _vals()
        A = [list(d) for d in g[:5]]
        one = T.pick_far(vals, vals, [A])
        self.assertTrue(one["found"] and one["exact"])
        B = [list(q) for _, q in one["decks"]]
        self.assertLessEqual(T.SIM.pair_jaccard(A, B), 0.2 + 1e-12)
        two = T.pick_far(vals, vals, [A, B])
        if two["found"]:
            C = [list(q) for _, q in two["decks"]]
            self.assertLessEqual(T.SIM.pair_jaccard(A, C), 0.2 + 1e-12)
            self.assertLessEqual(T.SIM.pair_jaccard(B, C), 0.2 + 1e-12)
            self.assertLessEqual(two["total"], one["total"] + 1e-9)

    def test_subs_change_one_or_two_decks(self):
        g, vals = _vals()
        rep = [(vals[frozenset(d)][0], d) for d in g[:5]]
        ss = T.subs(rep, vals, set(), floor=0.0)
        self.assertTrue(ss)
        for s in ss:
            self.assertIn(len(s["changed"]), (1, 2))
            self.assertGreaterEqual(s["J"], T.J_SUB)
        self.assertEqual(sorted(s["total"] for s in ss)[::-1], [s["total"] for s in ss])
        shown = T.order_subs(ss)[:T.SHOW]
        self.assertEqual(len(shown), min(T.SHOW, len(ss)))


if __name__ == "__main__":
    unittest.main()
