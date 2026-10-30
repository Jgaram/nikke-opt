"""실험 12 분석(analyze12.py) — 합성 자료로 판단 규칙을 확인한다."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP12 = ROOT / "experiments" / "12_precompute_seeds"
if str(EXP12) not in sys.path:
    sys.path.insert(0, str(EXP12))

import analyze12 as Z  # noqa: E402

VAL = Z.VAL


def runs_with(ratios):
    """ratios: {기법: {예산: [시나리오별 K 대비 배율]}} → 실행 dict."""
    out = {}
    for s in VAL:
        for b in Z.BUDGETS:
            out[(s, 177, "K", b)] = {"final": {"total": 100.0}}
    for m, per in ratios.items():
        for b, rs in per.items():
            for s, r in zip(VAL, rs):
                out[(s, 177, m, b)] = {"final": {"total": 100.0 * r}}
    return out


def pre_of(name, final, hist, seed=0, kind="PB15", **kw):
    return {"name": name, "seed": seed, "kind": kind, "evals": 15000, "sims": 13000, "seconds": 1.0,
            "final": {"total": final, "squads": []}, "history": hist, "set_totals": [final, final - 1], "kicks": [], **kw}


GOOD = [1.0] * 8
BAD = [0.95] * 3 + [1.0] * 5   # −3% 밑 3개 → 못지않다 아님


class TestJudge(unittest.TestCase):
    def test_q1_counts(self):
        T = Z.totals(runs_with({m: {800: GOOD, 2000: GOOD} for m in Z.ALL_PB15}))
        q = Z.judge1(T)
        self.assertEqual((q["n_ok"], q["line"]), (3, 3))
        T = Z.totals(runs_with({"PB15": {800: GOOD, 2000: GOOD}, "PB15s1": {800: GOOD, 2000: GOOD},
                                "PB15s2": {800: BAD, 2000: GOOD}, "PB15s3": {800: GOOD, 2000: GOOD}}))
        self.assertEqual(Z.judge1(T)["n_ok"], 2)
        T = Z.totals(runs_with({"PB15s1": {800: GOOD, 2000: BAD}}))
        q = Z.judge1(T)
        self.assertEqual(q["line"], 1)
        self.assertFalse(q["complete"])

    def test_retry_seed(self):
        hi = [{"evals": 9000, "pack": 196.0}]
        lo = [{"evals": 9000, "pack": 190.0}]
        pre = {"PB15s1": pre_of("PB15s1", 199, hi, 1), "PB15s2": pre_of("PB15s2", 191, lo, 2),
               "PB15s3": pre_of("PB15s3", 189, lo, 3)}
        r = Z.retry_seed(pre)
        self.assertEqual(r["failed"], ["PB15s2", "PB15s3"])
        self.assertEqual((r["pick"], r["seed"]), ("PB15s3", 3))

    def test_targets_and_q2(self):
        h_early = [{"evals": 8000, "pack": 196.0}]
        h_late = [{"evals": 12000, "pack": 196.0}]
        pre = {m: pre_of(m, 200.0, h_late) for m in Z.ALL_PB15}
        pre["PBD"] = pre_of("PBD", 199.0, h_early, kind="PBD")     # (a)만
        pre["PBS"] = pre_of("PBS", 203.0, h_late, kind="PBS")      # (b)만 (≥ 202)
        pre["PBDs3"] = pre_of("PBDs3", 190.0, [], 3, kind="PBD")   # 미도달 → 대상 없음
        tg = Z.targets(pre)
        self.assertEqual([m for m, _ in tg["PBD"]], ["PBD10k"])
        self.assertEqual([m for m, _ in tg["PBS"]], ["PBS"])
        self.assertEqual(tg["PBDs3"], [])
        T = Z.totals(runs_with({"PBD10k": {800: GOOD, 2000: GOOD}, "PBS": {800: GOOD, 2000: BAD}}))
        q2 = Z.judge2(T, pre)
        self.assertTrue(q2["per"]["PBD"]["verdict"].startswith("사전 계산 2/3로 유망"))
        self.assertTrue(q2["per"]["PBS"]["verdict"].startswith("효과 없음"))
        self.assertTrue(q2["per"]["PBDs3"]["verdict"].startswith("효과 없음"))
        self.assertEqual(q2["early"], ["PBD"])
        q2b = Z.judge2(Z.totals(runs_with({})), pre)
        self.assertTrue(q2b["per"]["PBD"]["verdict"].startswith("판단 불가"))

    def test_next_step(self):
        q1 = {"n_ok": 3}
        self.assertIn("채택 유지", Z.next_step(q1, {"promising": [], "early": []}))
        self.assertIn("10k", Z.next_step(q1, {"promising": ["PBD"], "early": ["PBD"]}))
        self.assertIn("시드 묶기", Z.next_step({"n_ok": 1}, {"promising": [], "early": []}))
        self.assertIn("기본 교체", Z.next_step({"n_ok": 2}, {"promising": ["PBS"], "early": []}))

    def test_render_with_real_logs(self):
        runs = Z.load_runs(None, None)  # 실험 10 · 11 기록만
        pre = Z.load_precompute([])
        a = Z.analyze(runs, pre)
        self.assertIn("PB15", [r["name"] for r in a["pre"]])
        s0 = [r for r in a["pre"] if r["name"] == "PB15"][0]
        self.assertTrue(s0["core"])
        self.assertEqual(s0["t195"], 12736)
        self.assertTrue(a["q1"]["stats"]["PB15"][2000]["noninf"])  # 실험 11 판단 재현
        text = Z.render(a)
        self.assertIn("질문 1", text)
        self.assertTrue(a["missing"])


if __name__ == "__main__":
    unittest.main()
