"""실험 18(run18.py) — 정책(PS · PF · PF2)의 고정점 · 비용 셈을 합성 자료로, 기록 재사용을 실험 17 기록으로 확인한다."""

import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parent.parent
EXP18 = ROOT / "experiments" / "18_deck_post"
if str(EXP18) not in sys.path:
    sys.path.insert(0, str(EXP18))

import run18 as R  # noqa: E402

BY = {s: sorted(n for n, b in R.R17.R16.BURST.items() if b == s and not n.startswith("test_")) for s in "123"}


def fake_book(n=300, seed=1):
    rng = random.Random(seed)
    best = {}
    while len(best) < n:
        frame = rng.choice(((1, 2, 2), (1, 1, 3), (2, 1, 2)))
        sq = []
        for s, c in zip("123", frame):
            sq += rng.sample(BY[s][:20], c)
        best.setdefault(frozenset(sq), (rng.uniform(20, 50), tuple(sq)))
    return best


class TestPolicies(unittest.TestCase):
    def test_fixed_point(self):
        best = fake_book()
        rng = random.Random(7)
        gain = {sq: rng.uniform(0.0, 0.08) for _, sq in best.values()}
        asked = []

        def value(squads):
            asked.append(list(squads))
            return {sq: best[frozenset(sq)][0] * (1 + gain[sq]) for sq in squads}

        r = R.run_policy("PF", best, value)
        tot, decks = R.pack(best, {sq: best[frozenset(sq)][0] * (1 + gain[sq]) for l in asked for sq in l})
        self.assertAlmostEqual(r["total"], tot)
        self.assertEqual(r["in_5deck_processed"], 5)          # 고정점: 최종 5덱은 모두 운용을 찾은 덱
        self.assertEqual(r["post"], sum(len(x) for x in asked))
        self.assertEqual(len({sq for l in asked for sq in l}), r["post"])   # 같은 구성을 두 번 묻지 않는다
        base, _ = R.pack(best, {})
        self.assertGreaterEqual(r["total"], base)

        asked.clear()
        ps = R.run_policy("PS", best, value)
        self.assertEqual(ps["rounds"], 1)
        self.assertEqual(ps["post"], len(R.top_per_frame(best)))

        asked.clear()
        p2 = R.run_policy("PF2", best, value)
        self.assertGreaterEqual(p2["post"], r["post"])
        self.assertIn("alt_total", p2)
        self.assertLessEqual(p2["alt_total"], p2["total"] + 1e-9)

    def test_reuse_exp17(self):
        import json
        t17 = json.loads((R.EXP17 / "run_log" / "targets.json").read_text(encoding="utf-8"))
        c = t17["scenarios"]["v1"]["comps"][0]
        if not (R.EXP17 / "run_log" / "logs" / "J" / f"{R.hname(c['id'])}.jsonl.gz").exists():
            self.skipTest("실험 17 기록 없음")
        ops = R.Ops(None, {}, t17["inventory"], out=Path("/nonexistent"), reuse=True)
        for m in R.METHODS:
            r = ops.get(m, "v1", c["squad"])
            self.assertIsNotNone(r["value"])
            self.assertIn(r["source"], ("exp16", "exp17"))
        self.assertGreaterEqual(ops.get("S", "v1", c["squad"])["value"], ops.get("C", "v1", c["squad"])["value"])
        with self.assertRaises(RuntimeError):
            ops.get("C", "v1", ["크라운", "리타", "헬름", "라피 : 레드 후드", "미란다"])


if __name__ == "__main__":
    unittest.main()
