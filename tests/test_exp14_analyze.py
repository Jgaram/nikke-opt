"""실험 14 분석(analyze14.py) — 합성 자료로 판단 규칙을 확인한다."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = ROOT / "experiments" / "14_seed_pairs"
if str(p) not in sys.path:
    sys.path.insert(0, str(p))

import analyze14 as X  # noqa: E402
from tests.test_exp13_analyze import BAD, GOOD, T_of  # noqa: E402


def single(final, t):
    return {"final": {"total": final, "squads": []}, "history": [{"evals": t, "pack": 196.0}] if t else []}


SINGLES = {4: single(197, 9000), 5: single(193, None), 6: single(192, None), 7: single(193, None)}


class TestJudge14(unittest.TestCase):
    def test_both_pass(self):
        j = X.judge(T_of({"U2a": {800: GOOD, 2000: GOOD}, "U2b": {800: GOOD, 2000: GOOD}}), SINGLES)
        self.assertEqual(j["n_ok"], 2)
        self.assertIn("바꾼다", j["text"])
        self.assertIn("신캐", j["next"])
        self.assertIsNone(j["u4n"])
        self.assertTrue(j["per"]["U2b"]["both_failed"])
        self.assertFalse(j["per"]["U2a"]["both_failed"])

    def test_fail_then_u4n(self):
        base = {"U2a": {800: GOOD, 2000: GOOD}, "U2b": {800: BAD, 2000: GOOD}}
        j = X.judge(T_of(base), SINGLES)
        self.assertEqual(j["n_ok"], 1)
        self.assertIn("판단 불가", j["text"])
        j = X.judge(T_of({**base, "U4n": {800: GOOD, 2000: GOOD}}), SINGLES)
        self.assertIn("시드 4개", j["next"])
        j = X.judge(T_of({**base, "U4n": {800: BAD, 2000: GOOD}}), SINGLES)
        self.assertIn("PBD", j["next"])
        self.assertIsNone(X.judge(T_of({"U2a": {800: GOOD}}), SINGLES)["n_ok"])

    def test_real_logs(self):
        runs = X.load_runs(None, None)
        singles = X.load_singles(None)
        self.assertEqual(sorted(singles), [0, 1, 2, 3])
        a = X.analyze(runs, singles, {}, [])
        self.assertEqual(a["n_failed"], 1)  # s2만 195억 미도달
        self.assertTrue(a["old"]["U4"]["ok"])  # 실험 13 판단 재현
        self.assertIn("판단 불가", X.render(a))
        self.assertEqual(len(a["missing"]), 2 * 2 * 8)


if __name__ == "__main__":
    unittest.main()
