"""실험 29(C 근처 탐색 + 후처리 · 세부 분류 후처리) — 평가기 없이."""

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


R = sys.modules.get("run29") or _load("run29", ROOT / "experiments" / "29_tree_post" / "run29.py")


def _book():
    g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJKLMNO"]
    book = {frozenset(d): (20.0 - i, d) for i, d in enumerate(g)}
    for s in range(1, 5):
        for c in range(5):
            d = tuple(g[(r + s * c) % 15][(c + r) % 5] for r in range(5))
            if len(set(x[0] for x in d)) == 5:
                book.setdefault(frozenset(d), (14.0 - 0.1 * c - s, d))
    return g, book


class TestRun29(unittest.TestCase):
    def test_settings_match_exp27(self):
        self.assertEqual((R.THETA, R.EXTRA, R.ROUND, R.RESERVE), (0.2, 1000, 100, 125))
        self.assertEqual((R.ALT_RATIO, R.PASS_COUNT), (0.97, 6))
        self.assertEqual(R.METHOD, R.R27.METHOD)

    def test_pick_c_respects_both_refs_and_keeps_prev(self):
        g, book = _book()
        A = [d for d in g[:5]]
        B = [d for d in g[5:10]]
        p = R.pick_c(book, [A, B], {})
        self.assertTrue(p["found"])
        for ref in (A, B):
            self.assertLessEqual(R.SIM.pair_jaccard([list(q) for q in ref], p["decks"]), 0.2 + 1e-12)
        self.assertTrue(R.within(p["decks"], [[frozenset(q) for q in A], [frozenset(q) for q in B]], p["budget"]))
        # 더 낮은 해가 나와도 직전 C를 지킨다
        worse = dict(p, total=p["total"])
        again = R.pick_c(book, [A, B], {}, prev=worse)
        self.assertGreaterEqual(again["total"], p["total"] - 1e-9)
        boosted = R.pick_c(book, [A, B], {g[12]: 100.0})
        self.assertGreater(boosted["total"], p["total"])

    def test_build_tree_and_shown_need(self):
        g, book = _book()
        A = [(book[frozenset(d)][0], d) for d in g[:5]]
        B = [(book[frozenset(d)][0], d) for d in g[5:10]]
        vals = R.vals_of(book, {})
        tree = R.build_tree(sum(v for v, _ in A), {"A": A, "B": B}, vals, set())
        self.assertEqual([k["name"] for k in tree], ["A", "B"])
        a = tree[0]
        self.assertTrue(a["subs"])
        for s in a["subs"]:
            self.assertEqual(set(s["J_other"]), {"B"})
            self.assertEqual(len(s["new_values"]), len(s["new_decks"]))
        need = R.shown_need(tree, vals, {})
        self.assertTrue(need)
        self.assertEqual(R.shown_need(tree, vals, {sq: 1.0 for sq in need}), [])

    def test_verdict(self):
        self.assertTrue(R.verdict([0.98] * 6 + [0.9] * 2).startswith("통과"))
        self.assertTrue(R.verdict([0.98] * 5 + [0.9] * 3).startswith("미통과"))


if __name__ == "__main__":
    unittest.main()
