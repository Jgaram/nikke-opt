"""실험 30(속성별 사전 계산 5덱 지도) — 평가기 없이."""

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


R = sys.modules.get("run30") or _load("run30", ROOT / "experiments" / "30_element_map" / "run30.py")


def _book():
    """니케 75명(15줄 × 5). 줄 덱 15개가 가장 좋고, 대각 덱은 그보다 낮다 — 서로 먼 5덱이 여럿 있다."""
    g = [tuple(f"{r}{c}" for c in range(5)) for r in "ABCDEFGHIJKLMNO"]
    book = {frozenset(d): (20.0 - 0.1 * i, d) for i, d in enumerate(g)}
    for s in range(1, 5):
        for c in range(5):
            d = tuple(g[(r + s * c) % 15][(c + r) % 5] for r in range(5))
            if len(set(x[0] for x in d)) == 5:
                book.setdefault(frozenset(d), (14.0 - 0.1 * c - s, d))
    return g, book


class TestRun30(unittest.TestCase):
    def test_registered_values(self):
        self.assertEqual(R.ELEMENTS, ("전격", "풍압", "철갑", "수냉", "작열"))
        self.assertEqual((R.SEED_BUDGET, R.PREFIX, R.W_BUDGET), (12500, 6250, 12500))
        self.assertEqual(2 * R.SEED_BUDGET, 2 * R.PREFIX + R.W_BUDGET)        # B와 W의 총평가가 같다
        self.assertEqual((R.BLOCK, R.BLOCK_ORDER, R.THETA, R.NEW_MIN, R.MAX_REPS), (1000, 125, 0.2, 0.90, 10))
        self.assertEqual((R.GOOD, R.LOW, R.CORE_N, R.CORE_PX), (0.97, 0.95, 2000, 30))

    def test_options(self):
        self.assertEqual(R.options("작열"), {"enemy": {"code": "작열"}})
        self.assertEqual(R.options("풍압", 30), {"enemy": {"code": "풍압", "core_px": 30}})

    def test_class_map_reps_are_far_apart(self):
        g, book = _book()
        m = R.class_map(book, limit=10, low=0.0, max_reps=3)
        self.assertEqual(len(m["reps"]), 3)
        self.assertAlmostEqual(m["best"], sum(20.0 - 0.1 * i for i in range(5)))
        plans = [r["decks"] for r in m["reps"]]
        for i in range(len(plans)):
            for j in range(i):
                self.assertLessEqual(R.SIM.pair_jaccard(plans[i], plans[j]), 0.2 + 1e-12)
        self.assertEqual(R.count_at(m, m["best"], good=0.0), 3)
        self.assertEqual(R.count_at(m, m["best"], good=1.0), 1)

    def test_pick_far30_matches_exp28(self):
        g, book = _book()
        for refs in ([g[:5]], [g[:5], g[5:10]]):
            a = R.pick_far30(book, book, refs, 0.2, 10)
            b = R.T28.pick_far(book, book, refs, 0.2, 10)
            self.assertEqual((a["found"], a["total"], a["decks"], a["exact"]), (b["found"], b["total"], b["decks"], b["exact"]))

    def test_pick_far30_respects_limit(self):
        import random
        import time
        rng = random.Random(0)
        names = [f"n{i}" for i in range(120)]
        book = {}
        while len(book) < 6000:
            sq = tuple(rng.sample(names, 5))
            book.setdefault(frozenset(sq), (rng.random() * 10 + 50, sq))
        ref = [q for _, q in R.R9.pack_vals(book)[1]]
        t = time.monotonic()
        p = R.pick_far30(book, book, [ref], 0.2, 0.5)
        self.assertLess(time.monotonic() - t, 5.0)
        self.assertTrue(p["found"])

    def test_pick_target_keeps_prev_only_if_feasible(self):
        g, book = _book()
        A = [g[i] for i in range(5)]
        p = R.pick_target(book, [A], None)
        self.assertTrue(p["found"])
        # 직전 대표가 기준과 너무 가까우면(= A 자체) 쓰지 않는다
        q = R.pick_target(book, [A], [list(d) for d in A])
        self.assertLessEqual(R.SIM.pair_jaccard([list(d) for d in A], q["decks"]), 0.2 + 1e-12)
        # 가능한 직전 대표는 floor로 지킨다
        r = R.pick_target(book, [A], p["decks"])
        self.assertGreaterEqual(r["total"], p["total"] - 1e-9)
        # 기준이 없으면 최선
        self.assertAlmostEqual(R.pick_target(book, [], None)["total"], R.R9.pack_vals(book)[0])

    def test_core_candidates_keep_plans_and_slot_swaps(self):
        g, book = _book()
        m = R.class_map(book, limit=10, low=0.0, max_reps=2)
        cands = R.core_candidates(book, [m], n=30)
        self.assertEqual(len(cands), len(set(frozenset(q) for q in cands)))
        reps = list(dict.fromkeys(frozenset(q) for r in m["reps"] for q in r["decks"]))   # 대표끼리 덱 하나는 같을 수 있다
        self.assertTrue(len(reps) < len(cands) <= 30)                                    # 작은 책이라 후보가 30개보다 적을 수 있다
        self.assertEqual([frozenset(q) for q in cands[:len(reps)]], reps)
        # 나머지는 어떤 대표의 덱 하나를 바꾼 것: 그 대표의 다른 4덱과 겹치지 않는다
        plans = [[frozenset(q) for q in r["decks"]] for r in m["reps"]]
        for q in cands[len(reps):]:
            c = frozenset(q)
            self.assertTrue(any(any(not (c & frozenset().union(*(d for j, d in enumerate(pl) if j != i))) for i in range(5))
                                for pl in plans))
        # 후보만으로 대표 1번(최선)이 다시 짜진다
        self.assertAlmostEqual(R.R9.pack_vals({frozenset(q): book[frozenset(q)] for q in cands})[0], m["best"])

    def test_known_evaluator(self):
        class Fake:
            version = {"repo": "x", "commit": "y"}
            sim_count = 0

            def evaluate(self, reqs):
                Fake.sim_count += len(reqs)
                from nikke_opt.evaluator import EvalResult
                return [EvalResult(7, {}) for _ in reqs]

        from nikke_opt.evaluator import EvalRequest
        ev = R.KnownEvaluator(Fake(), {("a", "b"): 5})
        res = ev.evaluate([EvalRequest(("a", "b")), EvalRequest(("b", "a")), EvalRequest(("c",))])
        self.assertEqual([r.total_damage for r in res], [5, 7, 7])
        self.assertTrue(res[0].cached)
        self.assertEqual((ev.known_hits, ev.sim_count), (1, 2))

    def test_verdict(self):
        row = lambda dm, br: {"dM": dm, "best_ratio": br}
        self.assertEqual(R.verdict([row(1, 1.0)] * 4 + [row(0, 0.999)]), "넓게 찾기가 지도를 넓힌다")
        self.assertEqual(R.verdict([row(2, 0.99)] * 5), "지도는 넓지만 최선이 낮다")
        self.assertEqual(R.verdict([row(0, 1.0)] * 5), "차이 없음")
        self.assertEqual(R.verdict([row(-1, 1.0)] * 5), "기준선이 낫다")
        self.assertEqual(R.verdict([row(1, 1.0)] * 3 + [row(-1, 1.0)] * 2), "차이 없음")


if __name__ == "__main__":
    unittest.main()
