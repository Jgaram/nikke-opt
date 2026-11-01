"""실험 20(accounts20 · run20 · analyze20) — 개발 계정 고정 · 주력 딜러 · 유력 대안 · 두 계보 탐색 · 판단 규칙(가짜 평가기, 시뮬 없음)."""

import json
import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP20 = ROOT / "experiments" / "20_search_robust"
if str(EXP20) not in sys.path:
    sys.path.insert(0, str(EXP20))

import accounts20 as A20  # noqa: E402
import analyze20 as AN  # noqa: E402
import run20 as R  # noqa: E402


class _Res:
    def __init__(self, sq, w):
        dm = [int(w[n] * (1 + 0.1 * i) * 1e7) for i, n in enumerate(sq)]
        self.total_damage = sum(dm) + (int(3e8) if len({len(n) for n in sq}) <= 3 else 0)
        self.raw = {"members": [{"name": n, "damage": d} for n, d in zip(sq, dm)]}
        self.error, self.cached = None, False


class FakeEv:
    def __init__(self):
        rng = random.Random(5)
        self.w = {n: rng.uniform(1, 10) for n in R.R10.P177}
        self.sim_count = 0

    def evaluate(self, reqs):
        self.sim_count += len(reqs)
        return [_Res(r.squad, self.w) for r in reqs]


class TestAccounts(unittest.TestCase):
    def test_fixed(self):
        a, b = A20.new_dev_scenarios(), A20.new_dev_scenarios()
        self.assertEqual(a, b)
        self.assertEqual([s["id"] for s in a], ["d1", "d2", "d3", "d4"])
        for s in a[:3]:
            self.assertNotIn(A20.CB.DEFAULT_CUBE, s["cubes"])
            self.assertEqual(s["start_cube"], "택티컬 베어 큐브")
        self.assertEqual(a[2]["cubes"]["택티컬 베어 큐브"], 8)
        self.assertEqual((a[3]["start_cube"], a[3]["cubes"][A20.CB.DEFAULT_CUBE]), (A20.CB.DEFAULT_CUBE, 3))
        self.assertEqual([s["id"] for s in A20.dev_scenarios()], [f"t{i}" for i in range(1, 9)] + ["d1", "d2", "d3", "d4"])


class TestLeaders(unittest.TestCase):
    def test_leader_of_raw(self):
        raw = {"members": [{"name": "가", "damage": 5}, {"name": "나", "damage": 9}, {"name": "다", "damage": 9}]}
        self.assertEqual(R.leader_of_raw(raw), "다")
        self.assertIsNone(R.leader_of_raw({}))

    def test_leader_alt(self):
        rng = random.Random(2)
        names = [f"n{i}" for i in range(40)]
        best, leader = {}, {}
        for _ in range(300):
            sq = tuple(rng.sample(names, 5))
            c = frozenset(sq)
            best[c] = (rng.uniform(10, 40), sq)
            leader[c] = sq[0]
        t, decks = R.R18.pack(best, {})
        lead = [leader[frozenset(sq)] for _, sq in decks]
        at, alt, pair = R.leader_alt(best, {}, lead, leader)
        self.assertEqual(len(alt), 5)
        self.assertLessEqual(at, t)
        la = [leader[frozenset(sq)] for _, sq in alt]
        self.assertGreaterEqual(len(set(la) - set(lead)), 2)
        self.assertFalse(set(pair) & set(la))

    def test_rebuild_alt(self):
        rng = random.Random(9)
        names = [f"n{i}" for i in range(35)]
        best, leader = {}, {}
        for _ in range(400):
            sq = tuple(rng.sample(names, 5))
            c = frozenset(sq)
            best[c] = (rng.uniform(10, 40), sq)
            leader[c] = sq[0]
        t, decks = R.R18.pack(best, {})
        bsq = [sq for _, sq in decks]
        at, alt, pair = R.rebuild_alt(best, {}, bsq, leader)
        self.assertEqual(len(alt), 5)
        shape = R.alt_shape(bsq, [sq for _, sq in alt], leader)
        self.assertGreaterEqual(shape["rebuilt"], 2)
        self.assertGreaterEqual(shape["new_leaders"], 2)
        self.assertLessEqual(at, t)

    def test_policy_pf_matches_exp18(self):
        rng = random.Random(4)
        names = [f"n{i}" for i in range(30)]
        best = {}
        for _ in range(200):
            sq = tuple(rng.sample(names, 5))
            best[frozenset(sq)] = (rng.uniform(10, 40), sq)
        val = lambda sqs: {sq: best[frozenset(sq)][0] * (1 + (hash(sq) % 7) / 100) for sq in sqs}
        a = R.R18.run_policy("PF", best, val)
        b = R.policy_pf(best, val)
        self.assertEqual((a["total"], a["decks"]), (b["total"], b["decks"]))


class TestTwoLineages(unittest.TestCase):
    def test_prefix_and_budget(self):
        sc = A20.new_dev_scenarios()[1]
        acct = R.AC.AccountT(sc)
        pre = json.loads(R.R19.PRE["U4"].read_text(encoding="utf-8"))
        R.R10.pack_alt20 = lambda *x, **k: (0.0, [])
        summ, recs = R.run_two(acct, 600, FakeEv(), pre)
        self.assertLessEqual(summ["evals"], 600)
        self.assertTrue(any(h.get("lineage") == "B" for h in summ["history"]))
        self.assertTrue(all(r["leader"] for r in recs if r["total_damage"] is not None))
        s0, r0, _ = R.R10.run_method(acct, "P", 600, FakeEv(), pre=pre, pool=177)
        k = summ["b_start"]["evals"]
        self.assertEqual([r["squad"] for r in recs[:k]], [r["squad"] for r in r0[:k]])   # 첫 계보 = 같은 예산 U4의 앞부분


class TestJudge(unittest.TestCase):
    def test_cheapest_eligible(self):
        q = {"C0": [1.0] * 11 + [0.97], "C3": [1.0] * 11 + [0.985], "CL3": [1.0] * 11 + [0.99], "REF": [1.0] * 12}
        v = AN.judge(q)
        self.assertEqual((v["pick"], v["met"]), ("CL3", True))
        q["CL3"] = q["C3"]
        self.assertEqual(AN.judge(q)["pick"], "C3")
        q["C0"] = [1.0] * 12
        self.assertEqual(AN.judge(q)["pick"], "C0")

    def test_none_eligible(self):
        q = {"C0": [0.95] * 12, "C3": [0.97] * 12, "CL3": [0.96] * 12, "REF": [0.975] * 12}
        v = AN.judge(q)
        self.assertEqual((v["pick"], v["met"]), ("REF", False))


if __name__ == "__main__":
    unittest.main()
