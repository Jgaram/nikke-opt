"""실험 39 골격: 검증 시즌 자료 · 판 인터페이스(시뮬 0)."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "experiments" / "39_bundle_explore"


def load():
    if "run39" in sys.modules:
        return sys.modules["run39"]
    spec = importlib.util.spec_from_file_location("run39", EXP / "run39.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run39"] = mod
    spec.loader.exec_module(mod)
    return mod


class Exp39(unittest.TestCase):
    def test_seasons_split(self):
        m = load()
        self.assertEqual(m.SEASONS, tuple(range(23, 33)))
        self.assertFalse(set(m.SEASONS) & set(m.DEV_SEASONS))

    def test_accounts(self):
        m = load()
        for s in (23, 32):
            acct = m.run31.account(s, 0)
            self.assertEqual(set(acct.names), set(m.run31.season(s)["pool"]))

    def test_base_round_is_exp10(self):
        m = load()
        self.assertIs(m.arm_round("base"), m.R10.local_round)

    def test_verdict(self):
        m = load()
        self.assertEqual(m.verdict([0.006] * 9 + [-0.02]), "좋음")
        self.assertEqual(m.verdict([0.0] * 10), "비김")
        self.assertEqual(m.verdict([0.01] * 7 + [-0.02] * 3), "나쁨")


if __name__ == "__main__":
    unittest.main()
