"""실험 9 실행기(run9.py) · 분석(analyze9.py) — 가짜 평가기로 확인한다."""

import json
import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

EXP9 = Path(__file__).resolve().parent.parent / "experiments" / "09_account_pack"
if str(EXP9) not in sys.path:
    sys.path.insert(0, str(EXP9))

import analyze9 as A  # noqa: E402
import run9  # noqa: E402


class _Res:
    def __init__(self, dmg):
        self.total_damage, self.error, self.cached = dmg, None, False


class FakeEv:
    """니케 가중치 + 짝 보너스 + 순서 약간. 결정론."""

    def __init__(self):
        rng = random.Random(7)
        self.w = {n: rng.uniform(1, 10) for n in run9.POOL}
        self.sim_count = 0
        self.asked = []

    def damage(self, sq, options):
        v = sum(self.w[n] for n in sq)
        v += sum(3.0 for a in sq for b in sq if a < b and (len(a) + len(b)) % 7 == 0)
        v += 0.01 * sum(i * self.w[n] for i, n in enumerate(sq))
        low = (options.get("profile") or {}).get("chars", {})
        v -= sum(2.0 for n in sq if n in low)
        return int(v * 1e8)

    def evaluate(self, reqs):
        self.sim_count += len(reqs)
        self.asked += [r.squad for r in reqs]
        return [_Res(self.damage(r.squad, r.options)) for r in reqs]


class TestScenarios(unittest.TestCase):
    def test_dev_matches_exp5(self):
        summ = json.loads((EXP9.parent / "05_roster_deficit" / "summary.json").read_text(encoding="utf-8"))["scenarios"]
        for d in run9.dev_scenarios():
            e = summ[d["name"]]
            self.assertEqual(sorted(e["missing"]), sorted(d["missing"]))
            self.assertEqual(e["tiers"], {k: v for k, v in d["tiers"].items() if v != "상"})

    def test_val_distinct_and_fixed(self):
        v = run9.val_scenarios()
        self.assertEqual([s["id"] for s in v], [f"v{i}" for i in range(1, 9)])
        self.assertEqual(v, run9.val_scenarios())
        dev = {tuple(s["missing"]) for s in run9.dev_scenarios() if s["missing"]}
        self.assertFalse(dev & {tuple(s["missing"]) for s in v if s["missing"]})
        mix = v[7]
        self.assertEqual(len(mix["missing"]), 3)
        self.assertFalse(set(mix["missing"]) & set(mix["tiers"]))

    def test_account_profile(self):
        a = run9.Account(run9.dev_scenarios()[7])
        self.assertEqual(len(a.options["profile"]["chars"]), 6)
        self.assertEqual(run9.Account(run9.dev_scenarios()[0]).options, {})


class TestPack(unittest.TestCase):
    def setUp(self):
        rng = random.Random(3)
        names = list(run9.POOL)
        self.book = run9.S4.Book()
        for _ in range(120):
            sq = tuple(rng.sample(names, 5))
            self.book.add(sq, rng.uniform(10, 40))

    def test_same_as_exp4(self):
        a = run9.S4.pack(self.book)
        b = run9.pack_vals(self.book.best)
        self.assertAlmostEqual(a[0], b[0])

    def test_avoid(self):
        best = run9.pack_vals(self.book.best)
        avoid = {frozenset(sq) for _, sq in best[1]}
        alt = run9.pack_vals(self.book.best, avoid=[avoid], max_share=2)
        self.assertLessEqual(sum(frozenset(sq) in avoid for _, sq in alt[1]), 2)
        self.assertLessEqual(alt[0], best[0])
        used = [n for _, sq in alt[1] for n in sq]
        self.assertEqual(len(used), len(set(used)))

    def test_frames_and_pattern(self):
        self.assertEqual(set(run9.PATTERN), set(run9.FRAMES))
        for f, pat in run9.PATTERN.items():
            self.assertEqual(len(pat), 5)


class TestMethods(unittest.TestCase):
    def test_all_methods(self):
        acct = run9.Account(run9.dev_scenarios()[2])
        for m in run9.METHODS:
            ev = FakeEv()
            summ, recs = run9.run_method(acct, m, 300, ev)
            self.assertLessEqual(summ["evals"], 300)
            self.assertEqual(len(ev.asked), len(set(ev.asked)))  # 같은 스쿼드를 두 번 묻지 않는다
            self.assertTrue(all(n in acct.owned for sq in ev.asked for n in sq))
            used = [n for _, sq in summ["final"]["squads"] for n in sq]
            self.assertEqual(len(used), 25)
            self.assertEqual(len(set(used)), 25)
            self.assertGreaterEqual(summ["final"]["total"], summ["history"][0]["pack"])
            if m == "L0":
                self.assertGreater(summ["transplant_players"], 30)
            else:
                self.assertEqual(summ["transplant_players"], run9.K_RANKERS)
            self.assertLessEqual(summ["transplant_evals"], 300 - 300 // 8)

    def test_build_decks_frames(self):
        acct = run9.Account(run9.dev_scenarios()[0])
        score = lambda c: float(len(c))  # noqa: E731
        decks = run9.build_decks(list(acct.owned), score)
        self.assertTrue(decks)
        for d in decks:
            self.assertEqual(len(set(d)), 5)
            self.assertIn(run9.frame(d), run9.FRAMES)

    def test_post_targets_and_repack(self):
        book = run9.S4.Book()
        acct = run9.Account(run9.dev_scenarios()[0])
        ev = FakeEv()
        summ, recs = run9.run_method(acct, "L0k", 300, ev)
        best = run9.book_of(recs)
        t = run9.post_targets(best, 2)
        per = {}
        for sq in t:
            per[run9.skeleton(sq)] = per.get(run9.skeleton(sq), 0) + 1
        self.assertTrue(all(v <= 2 for v in per.values()))
        post = {t[0]: best[frozenset(t[0])][0] * 2}
        total, ch = run9.repack_post(best, post)
        self.assertGreater(total, summ["final"]["total"])
        del book


class TestJudge(unittest.TestCase):
    @staticmethod
    def P(g):  # g: method → budget → [gain per scenario]
        out = {}
        for s in range(8):
            for b in A.BUDGETS:
                out[(f"v{s}", "L0", b)] = 100.0
                for m in A.METHODS[1:]:
                    out[(f"v{s}", m, b)] = 100.0 * (1 + g.get(m, {}).get(b, [0] * 8)[s])
        return out

    def test_line1(self):
        up = [0.01] * 6 + [-0.01, -0.02]
        j = A.judge(self.P({"L2": {800: up, 2000: up}, "L1": {300: up}}), [f"v{i}" for i in range(8)])
        self.assertEqual((j["line"], j["pick"]), (1, "L2"))
        self.assertEqual(j["small_budget"], ["L1"])

    def test_line2_3_and_worse(self):
        up = [0.01] * 6 + [-0.01, -0.02]
        j = A.judge(self.P({"L0k": {300: up, 800: up}}), [f"v{i}" for i in range(8)])
        self.assertEqual((j["line"], j["pick"]), (2, "L0k"))
        five = [0.01] * 5 + [-0.01] * 3
        down = [-0.01] * 6 + [0.01, 0.02]
        j = A.judge(self.P({"L1": {800: five, 2000: five}, "L2": {300: down}}), [f"v{i}" for i in range(8)])
        self.assertEqual(j["line"], 3)
        self.assertEqual(j["loses"]["L2"], [300])

    def test_both_pick_by_800(self):
        up, up2 = [0.01] * 8, [0.02] * 8
        j = A.judge(self.P({"L1": {800: up2, 2000: up}, "L2": {800: up, 2000: up2}}), [f"v{i}" for i in range(8)])
        self.assertEqual(j["pick"], "L1")


if __name__ == "__main__":
    unittest.main()
