"""실험 21(accounts21 · run21 · analyze21) — 검증 계정 고정 · 판 구성 · 판단 규칙(시뮬 없음)."""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP21 = ROOT / "experiments" / "21_first_goal_recheck"
if str(EXP21) not in sys.path:
    sys.path.insert(0, str(EXP21))

import accounts21 as A21  # noqa: E402
import analyze21 as AN  # noqa: E402
import run21 as R  # noqa: E402


class TestAccounts(unittest.TestCase):
    def test_fixed_and_new(self):
        a, b = A21.check_scenarios(), A21.check_scenarios()
        self.assertEqual(a, b)
        self.assertEqual([s["id"] for s in a], [f"u{i}" for i in range(1, 9)])
        no_bear = [s["id"] for s in a if A21.CB.DEFAULT_CUBE not in s["cubes"]]
        self.assertEqual(no_bear, ["u2", "u4", "u8"])
        self.assertEqual(a[5]["cubes"][A21.CB.DEFAULT_CUBE], 5)
        def key(s):
            return (tuple(s["missing"]), tuple(sorted(s["cubes"].items())), tuple(sorted(s["tiers"].items())),
                    tuple(sorted(s["ammo"].items())))
        dev = {key(s) for s in R.R20.A20.dev_scenarios()}
        self.assertFalse(any(key(s) in dev for s in a))   # 개발 계정과 같은 계정이 없다


class TestPlans(unittest.TestCase):
    def test_plans(self):
        old = R.P_RUN
        try:
            for p_run, ref in (("U4_3000", "U4_4000"), ("CL_3000", "U4_4000"), ("U4_4000", "U4_6000")):
                R.P_RUN = p_run
                ps = {k: run for k, run, *_ in R.plans()}
                self.assertEqual(ps["P"], p_run)
                self.assertEqual(ps["REF"], ref)
                self.assertEqual((ps["B1"], ps["P0"], ps["B0w"]), ("U4_2000", "U4_2000", "U4_4000"))
                self.assertIn(p_run, R.needed_runs())
        finally:
            R.P_RUN = old


class TestJudge(unittest.TestCase):
    def test_judge(self):
        v = AN.judge([0.01] * 8, [0.02] * 8, [1.0] * 7 + [0.985], 7, alt_min=6)
        self.assertTrue(v["passed"])
        v = AN.judge([0.01] * 8, [0.02] * 8, [1.0] * 7 + [0.975], 5, alt_min=6)
        self.assertFalse(v["first"])
        self.assertFalse(v["alt"])
        self.assertEqual([k for k, ok in v["criteria"].items() if not ok], [3, 6])


if __name__ == "__main__":
    unittest.main()
