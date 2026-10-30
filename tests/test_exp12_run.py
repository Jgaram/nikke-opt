"""실험 12 실행기(run12.py) — 가짜 평가기로 확인한다."""

import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP12 = ROOT / "experiments" / "12_precompute_seeds"
if str(EXP12) not in sys.path:
    sys.path.insert(0, str(EXP12))

import run12 as T  # noqa: E402
from tests.test_exp10_run import FakeEv, FlatEv  # noqa: E402

R10, R9, S4 = T.R10, T.R9, T.S4


class TestNames(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(T.parse_name("PB15s2"), ("PB15", 2, False))
        self.assertEqual(T.parse_name("PB15"), ("PB15", 0, False))
        self.assertEqual(T.parse_name("PBD"), ("PBD", 0, False))
        self.assertEqual(T.parse_name("PBSs3"), ("PBS", 3, False))
        self.assertEqual(T.parse_name("PBD10k"), ("PBD", 0, True))
        with self.assertRaises(ValueError):
            T.parse_name("PX")

    def test_seed_account(self):
        self.assertEqual(T.pre_account(0).id, "pre")  # 실험 11 PB15와 같은 시드
        self.assertEqual(T.pre_account(2).id, "pre-s2")
        self.assertEqual(len(T.pre_account(1).names), 177)


class TestVariants(unittest.TestCase):
    def test_seed_changes_start(self):
        ev = FakeEv()
        a, _, _ = R10.run_method(T.pre_account(0), "G+E", 300, ev, pool=177)
        b, _, _ = R10.run_method(T.pre_account(1), "G+E", 300, ev, pool=177)
        c, _, _ = R10.run_method(T.pre_account(1), "G+E", 300, ev, pool=177)
        self.assertNotEqual(a["start"], b["start"])
        self.assertEqual(b["final"], c["final"])  # 결정론

    def test_same_start_as_pb15(self):
        ev = FakeEv()
        _, r0, _ = R10.run_method(T.pre_account(0), "G+E", 800, ev, pool=177)
        for kind in ("PBD", "PBS"):
            summ, r1, _ = T.run_variant(T.pre_account(0), kind, 800, ev)
            n = summ["start"]["evals"]
            self.assertGreater(n, 100)
            self.assertEqual([x["squad"] for x in r0[:n]], [x["squad"] for x in r1[:n]])
            self.assertLessEqual(summ["evals"], 800)
            self.assertEqual(summ["errors"], 0)

    def test_pbd_waits_stall_rounds(self):
        ev = FlatEv()
        summ, _, _ = T.run_variant(T.pre_account(0), "PBD", 1600, ev)
        self.assertTrue(summ["kicks"])
        first = summ["kicks"][0]["evals"]
        self.assertGreaterEqual(first, summ["start"]["evals"] + T.STALL * R10.ROUND)
        ks = [k["evals"] for k in summ["kicks"]]
        self.assertTrue(all(b - a >= T.STALL * R10.ROUND for a, b in zip(ks, ks[1:])))  # 계보도 STALL 라운드 기다린다

    def test_pbs_climbers(self):
        ev = FakeEv()
        summ, recs, sess = T.run_variant(T.pre_account(0), "PBS", 1200, ev)
        self.assertFalse(summ["kicks"])
        self.assertTrue(summ["restarts"])
        phases = {r["phase"] for r in recs}
        self.assertIn("재시작", phases)
        self.assertIn("등반", phases)
        n_round = sum(r["phase"].startswith("탐색") for r in recs)
        n_climb = sum(r["phase"] in ("재시작", "등반") for r in recs)
        self.assertLessEqual(n_climb, n_round)  # 등반 몫 30% 이하
        self.assertTrue(all(x["end_val"] >= x["start_val"] for x in summ["restarts"]))

    def test_climb_excludes_best_pack(self):
        ev = FakeEv()
        acct = T.pre_account(0)
        sess = R9.Session(acct, ev, 2000)
        T.start_g(sess, acct, 250, R10.fit_for(177))
        best_used = {n for _, sq in sess.pack()[1] for n in sq}
        climbers, restarts = [], []
        n0 = len(sess.records)
        got = T.climb_round(sess, climbers, 30, R10.fit_for(177), random.Random(1), restarts)
        self.assertGreater(got, 0)
        self.assertLessEqual(got, 30)
        new = sess.records[n0:]
        starts = [r for r in new if r["phase"] == "재시작"]
        self.assertEqual(len(starts), T.CLIMB_N)
        for r in starts:
            self.assertFalse(set(r["squad"]) & best_used)
        for r in new:
            if r["phase"] == "등반":
                self.assertFalse(set(r["squad"]) & best_used)  # 출발이 최선 5덱 밖이고 교체도 그 밖에서

    def test_run_pre_and_truncate(self):
        ev = FakeEv()
        old = T.PRE_BUDGET
        try:
            T.PRE_BUDGET = 900
            out, recs = T.run_pre("PBSs1", ev)
        finally:
            T.PRE_BUDGET = old
        self.assertEqual(out["seed"], 1)
        self.assertEqual(out["kind"], "PBS")
        self.assertIn("t195", out)
        self.assertTrue(1 <= len(out["sets"]) <= R10.PRE_SETS)
        self.assertEqual(len(out["coef"]), 177)
        out["name"] = "PBSs1"
        cut = T.truncate(out, recs, 500)
        self.assertEqual(cut["evals"], 500)
        self.assertTrue(all(h["evals"] <= 500 for h in cut["history"]))
        self.assertLessEqual(cut["final"]["total"], out["final"]["total"] + 1e-9)
        self.assertEqual(cut["seed"], 1)

    def test_t_reach(self):
        h = [{"evals": 100, "pack": 190.0}, {"evals": 200, "pack": 195.0}, {"evals": 300, "pack": 199.0}]
        self.assertEqual(T.t_reach(h), 200)
        self.assertIsNone(T.t_reach(h[:1]))


if __name__ == "__main__":
    unittest.main()
