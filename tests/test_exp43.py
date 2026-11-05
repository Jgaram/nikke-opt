"""실험 43: 기록 경로가 이 실험을 가리키고, 판정 수치가 실험 39 · 42와 같다(시뮬 0)."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments" / "43_rulefree_verify"


def load():
    if "run43" in sys.modules:
        return sys.modules["run43"]
    spec = importlib.util.spec_from_file_location("run43", EXP / "run43.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run43"] = mod
    spec.loader.exec_module(mod)
    return mod


class Run43(unittest.TestCase):
    def test_log_redirect(self):
        r = load()
        self.assertEqual(r.R42.LOG, r.LOG)
        self.assertEqual(r.R42.vdir("R", 23), r.LOG / "verify" / "R" / "S23")
        self.assertTrue(str(r.R42.verify_recs.__code__.co_filename).endswith("run42.py"))

    def test_verdict_thresholds(self):
        r = load()
        R39 = r.r39()
        self.assertEqual((R39.GOOD, R39.BAD, R39.DROP, R39.MAX_DROPS, R39.BAD_DROPS), (0.005, -0.005, -0.01, 1, 3))
        self.assertEqual(r.verdict_of([0.0] * 10, 10)["verdict"], "비김")
        self.assertEqual(r.verdict_of([0.006] * 9 + [-0.02], 10)["verdict"], "좋음")
        self.assertEqual(r.verdict_of([0.0] * 7 + [-0.02] * 3, 10)["verdict"], "나쁨")
        self.assertTrue(r.verdict_of([0.0] * 3, 10)["verdict"].startswith("진행 중"))


if __name__ == "__main__":
    unittest.main()
