"""실험 15 분석(analyze15.py) — 합성 실행 결과로 경우 판단 · 미보유 손해 · 취합 규칙을 확인한다."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP15 = ROOT / "experiments" / "15_new_nikke"
if str(EXP15) not in sys.path:
    sys.path.insert(0, str(EXP15))

import analyze15 as X  # noqa: E402

VAL, VALN, P = X.VAL, X.VALN, X.POOL


def T_of(g: dict, base: float = 200.0, gn: dict | None = None) -> dict:
    """g: 기호 → G(F4 대비, 모든 시나리오 같은 값) 또는 시나리오별 리스트. 보유 800 · 2,000, 미보유 800."""
    T = {}
    for b in X.BUDGETS:
        for s in VAL:
            T[(s, P, X.BASE, b)] = base
            T[(s, P, X.K, b)] = base
    for s in VALN:
        T[(s, P, X.BASE, X.MISS_BUDGET)] = base
    for m, v in g.items():
        for b in X.BUDGETS:
            for i, s in enumerate(VAL):
                x = v[i] if isinstance(v, list) else v
                if x is not None:
                    T[(s, P, m, b)] = base * (1 + x)
    for m, v in (gn or {}).items():
        for s in VALN:
            T[(s, P, m, X.MISS_BUDGET)] = base * (1 + v)
    return T


class TestJudgeCase(unittest.TestCase):
    def test_order(self):
        self.assertEqual(X.judge_case(T_of({"O": 0.0, "I1": 0.0, "I2": 0.0}))["pick"], "O")
        self.assertEqual(X.judge_case(T_of({"O": -0.02, "I1": 0.0, "I2": 0.0}))["pick"], "I1")
        self.assertEqual(X.judge_case(T_of({"O": -0.02, "I1": -0.02, "I2": 0.001}))["pick"], "I2")
        self.assertEqual(X.judge_case(T_of({"O": -0.02, "I1": -0.02, "I2": -0.02}))["pick"], "F4")

    def test_low_count(self):
        two_low = [0.0] * 6 + [-0.05, -0.04]
        one_low = [0.0] * 7 + [-0.05]
        self.assertEqual(X.judge_case(T_of({"O": two_low, "I1": one_low, "I2": 0.0}))["pick"], "I1")

    def test_incomplete(self):
        part = [0.0] * 7 + [None]
        self.assertIsNone(X.judge_case(T_of({"O": part, "I1": 0.0, "I2": 0.0}))["pick"])
        self.assertIsNone(X.judge_case(T_of({"O": -0.02, "I2": 0.0}))["pick"])  # I1 없으면 I2로 건너뛰지 않는다
        self.assertEqual(X.judge_case(T_of({"O": -0.02, "I1": 0.0}))["pick"], "I1")  # I1 통과면 I2는 없어도 된다

    def test_missing_loss(self):
        m = X.judge_missing(T_of({}, gn={"O": 0.0, "I1": -0.02, "I2": -0.005}))
        self.assertEqual(m["loss"], {"I1": True, "I2": False})
        self.assertIsNone(X.judge_missing(T_of({}, gn={"O": 0.0}))["loss"]["I1"])


def per_of(ok: dict) -> dict:
    """경우 → {O, I1, I2: 통과 여부}."""
    return {c: {"n_new": len(X.W.CASES[c]), "judge": {"ok": dict(v)}, "missing": {"loss": {"I1": None, "I2": None}}}
            for c, v in ok.items()}


class TestAggregate(unittest.TestCase):
    def full(self, i1, i2, o=False):
        return per_of({c: {"O": o, "I1": a, "I2": b} for c, a, b in zip(X.W.META_CASES, i1, i2)})

    def test_rules(self):
        self.assertEqual(X.aggregate(self.full([True] * 4, [True] * 4))["rule"], "I1")
        self.assertEqual(X.aggregate(self.full([True, True, True, False], [True] * 4))["rule"], "I2")
        self.assertEqual(X.aggregate(self.full([False] * 4, [False] * 4))["rule"], "F4")
        g = X.aggregate(self.full([True, False, True, False], [False, False, True, False]))
        self.assertEqual(g["rule"], "split")
        self.assertIn("C1(n=1)", g["text"])
        self.assertIn("C4(n=10)", g["text"])

    def test_incomplete_and_c5(self):
        p = self.full([True] * 3, [True] * 3)
        self.assertIsNone(X.aggregate(p)["rule"])
        p = self.full([True] * 4, [True] * 4)
        p.update(per_of({"C5": {"O": False, "I1": True, "I2": True}}))
        g = X.aggregate(p)
        self.assertEqual(g["rule"], "I1")
        self.assertIn("예상과 다름", g["c5"])


class TestRender(unittest.TestCase):
    def test_case_render(self):
        T = T_of({"O": -0.02, "I1": 0.0, "I2": 0.0}, gn={"O": 0.0, "I1": 0.0, "I2": 0.0, "F4": 0.0})
        runs = {k: {"final": {"total": v, "squads": [[v / 5, ["아르카나 : 포츈 메이트", "토브"]]]}} for k, v in T.items()}
        a = X.analyze_case("C1", runs, {}, {"sims": 1})
        self.assertEqual(a["judge"]["pick"], "I1")
        self.assertEqual(a["missing_runs"], [])
        txt = X.render_case(a)
        self.assertIn("이어 붙이기로 충분(I1", txt)
        g = X.aggregate({"C1": a})
        self.assertIn("판단 불가", X.render_all({"C1": a}, g))


if __name__ == "__main__":
    unittest.main()
