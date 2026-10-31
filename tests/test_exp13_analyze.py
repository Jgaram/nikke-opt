"""실험 13 분석(analyze13.py) — 합성 자료로 판단 규칙을 확인한다."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP13 = ROOT / "experiments" / "13_seed_merge"
if str(EXP13) not in sys.path:
    sys.path.insert(0, str(EXP13))

import analyze13 as Y  # noqa: E402

VAL = Y.VAL
GOOD = [1.0] * 8
UP = [1.02] * 8
BAD = [0.95] * 3 + [1.0] * 5


def T_of(ratios):
    """ratios: {기법: {예산: [K 대비 배율]}} → totals."""
    T = {}
    for s in VAL:
        for b in Y.BUDGETS:
            T[(s, 177, "K", b)] = 100.0
    for m, per in ratios.items():
        for b, rs in per.items():
            for s, r in zip(VAL, rs):
                T[(s, 177, m, b)] = 100.0 * r
    return T


def obs_e3(n_core):
    return [{"kind": "E3", "core": i < n_core} for i in range(4)]


class TestJudge(unittest.TestCase):
    def test_q1_q2(self):
        T = T_of({"U4": {800: GOOD, 2000: GOOD}, "U2w": {800: BAD, 2000: GOOD}})
        self.assertTrue(Y.judge_k(T, "U4", "y", "n")["ok"])
        self.assertFalse(Y.judge_k(T, "U2w", "y", "n")["ok"])
        self.assertIsNone(Y.judge_k(T_of({"U4": {800: GOOD}}), "U4", "y", "n")["ok"])

    def test_q3(self):
        T = T_of({"PB15s3": {800: GOOD, 2000: GOOD}, "U4": {800: UP, 2000: GOOD},
                  "PB15s1": {800: GOOD, 2000: GOOD}, "U2w": {800: GOOD, 2000: BAD}})
        self.assertEqual(Y.judge3(T, "U4", "PB15s3")["verdict"], "better")
        self.assertEqual(Y.judge3(T, "U2w", "PB15s1")["verdict"], "pick")
        T2 = T_of({"PB15s3": {800: GOOD, 2000: GOOD}, "U4": {800: GOOD, 2000: GOOD}})
        self.assertEqual(Y.judge3(T2, "U4", "PB15s3")["verdict"], "noninf")
        self.assertIsNone(Y.judge3(T2, "U2w", None)["verdict"])

    def test_next_step(self):
        ok, no, na = {"ok": True}, {"ok": False}, {"ok": None}
        q3 = {"U4": {"verdict": "noninf"}, "U2w": {"verdict": "pick"}}
        self.assertIn("PBD", Y.next_step(no, ok, q3, []))
        self.assertIn("시드 2개(고르기)", Y.next_step(ok, ok, q3, []))
        self.assertIn("M3", Y.next_step(ok, no, q3, obs_e3(3)))
        s = Y.next_step(ok, no, q3, obs_e3(2))
        self.assertIn("시드 4개(합치기)", s)
        self.assertIn("새 시드로 확인", s)
        self.assertIn("판단 불가", Y.next_step(na, ok, q3, []))
        self.assertIn("U2w", Y.next_step(ok, na, q3, []))

    def test_render_with_real_logs(self):
        runs = Y.load_runs(None, None)  # 실험 10~12 기록만
        a = Y.analyze(runs, {}, [])
        self.assertTrue(a["singles"]["PB15s3"][2000]["noninf"])  # 실험 12 판단 재현
        self.assertFalse(a["singles"]["PB15s2"][800]["noninf"])
        self.assertIsNone(a["q1"]["ok"])
        text = Y.render(a)
        self.assertIn("질문 1", text)
        self.assertEqual(len(a["missing"]), 2 * 2 * 8)  # U4 · U2w만 빠진다


if __name__ == "__main__":
    unittest.main()
