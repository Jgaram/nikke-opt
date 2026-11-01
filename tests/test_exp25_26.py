"""실험 25(J 상한 고르기 대안) · 26(대안 근처 짧은 탐색) — 평가기 없이."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXP25 = ROOT / "experiments" / "25_jpick_alt"
EXP26 = ROOT / "experiments" / "26_alt_local"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(EXP25))
R25 = sys.modules.get("run25") or _load("run25", EXP25 / "run25.py")
R26 = sys.modules.get("run26") or _load("run26", EXP26 / "run26.py")


class TestAccounts25(unittest.TestCase):
    def test_new_accounts_fixed_and_distinct(self):
        w = R25.A25.check_scenarios()
        u = R25.A25.A21.check_scenarios()
        self.assertEqual([s["id"] for s in w], [f"w{i}" for i in range(1, 9)])
        self.assertEqual([s["name"] for s in w], [s["name"] for s in u])          # 같은 계정 모양
        self.assertEqual(R25.A25.A21.SEED_CHECK, 20261103)                        # 실험 21 시드를 되돌린다
        self.assertEqual(w, R25.A25.check_scenarios())                            # 결정론
        diff = sum(a["missing"] != b["missing"] or a["tiers"] != b["tiers"] or a["ammo"] != b["ammo"]
                   or a["cubes"] != b["cubes"] for a, b in zip(w, u))
        self.assertGreaterEqual(diff, 7)


class TestJPacker(unittest.TestCase):
    def test_respects_pair_budget(self):
        g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGH"]
        best = {frozenset(d): (10.0 - i, d) for i, d in enumerate(g)}
        swap = [("A0", "B1", "B2", "B3", "B4"), ("B0", "A1", "A2", "A3", "A4")]
        for d in swap:
            best[frozenset(d)] = (9.5, d)
        bdecks = g[:5]
        flags = {}
        pk = R25.jpacker(best, bdecks, 0.3, flags)
        t, d = pk({})
        plan = [list(q) for _, q in d]
        self.assertEqual(len(plan), 5)
        self.assertLessEqual(R25.SIM.pair_jaccard([list(q) for q in bdecks], plan), 0.3 + 1e-12)
        t2, _ = pk({g[5]: 100.0})                 # 운용 값이 기본보다 크면 그 값으로 묶는다
        self.assertGreater(t2, t)
        self.assertEqual(flags, {})

    def test_verdict(self):
        self.assertTrue(R25.verdict([0.98] * 6 + [0.9] * 2).startswith("통과"))
        self.assertTrue(R25.verdict([0.98] * 5 + [0.9] * 3).startswith("미통과"))


class TestRun26(unittest.TestCase):
    def test_apply_move_and_plan_cost(self):
        decks = [("a", "b", "c", "d", "e"), ("f", "g", "h", "i", "j")]
        moved = R26.apply_move(decks, [("a", "b", "c", "d", "f"), ("e", "g", "h", "i", "j")])
        self.assertEqual(moved, [("a", "b", "c", "d", "f"), ("e", "g", "h", "i", "j")])
        best = [frozenset("abcde"), frozenset("fghij")]
        self.assertEqual(R26.plan_cost(decks, best), 20)
        self.assertEqual(R26.plan_cost(moved, best), 12)

    def test_jpick_warm_start_same(self):
        g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJ"]
        book = {frozenset(d): (20.0 - i, d) for i, d in enumerate(g)}
        mix = [tuple(g[r][(c + r) % 5] for r in range(5)) for c in range(5)]
        for i, d in enumerate(mix):
            book[frozenset(d)] = (15.0 - 0.1 * i, d)
        cold = R26.jpick(book, 0.2)
        warm = R26.jpick(book, 0.2, prev=cold)
        self.assertEqual({frozenset(q) for q in cold["decks"]}, {frozenset(q) for q in warm["decks"]})
        self.assertAlmostEqual(cold["total"], warm["total"])
        self.assertTrue(warm["exact"])

    def test_verdict(self):
        self.assertEqual(R26.verdict([0.98] * 9 + [0.96] * 3, [0.96] * 12), "짧은 탐색으로 충분 · 대조보다 앞섬")
        self.assertEqual(R26.verdict([0.96] * 12, [0.96] * 12), "일부 · 대조와 비슷하거나 뒤짐")
        self.assertEqual(R26.verdict([0.93] * 12, [0.96] * 12), "더 큰 보강 필요")


if __name__ == "__main__":
    unittest.main()
